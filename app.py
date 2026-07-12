from flask import Flask, request, jsonify, session, send_from_directory, abort
from flask_socketio import SocketIO, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from pywebpush import webpush, WebPushException
import sqlite3
import json
import os
import logging
from functools import wraps

import game_engine as ge

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'game.db')
ASSET_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.mp3', '.ogg', '.wav', '.js', '.json'}

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pimp-empires-secret-key-change-in-production')

# Web Push (VAPID) - generated once on first run and persisted to a
# gitignored local file, never committed to source. The public key is
# handed to the client via /api/push/vapid-public-key rather than
# hardcoded there too, so it can only ever come from whatever key this
# specific server actually holds.
VAPID_KEYS_PATH = os.path.join(BASE_DIR, 'vapid_keys.json')


def _get_or_create_vapid_keys():
    if os.path.exists(VAPID_KEYS_PATH):
        with open(VAPID_KEYS_PATH) as f:
            keys = json.load(f)
        return keys['public'], keys['private']

    from py_vapid import Vapid02
    from cryptography.hazmat.primitives import serialization
    import base64

    v = Vapid02()
    v.generate_keys()
    pub_raw = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    public_key = base64.urlsafe_b64encode(pub_raw).decode().rstrip('=')
    priv_raw = v.private_key.private_numbers().private_value.to_bytes(32, 'big')
    private_key = base64.urlsafe_b64encode(priv_raw).decode().rstrip('=')

    with open(VAPID_KEYS_PATH, 'w') as f:
        json.dump({'public': public_key, 'private': private_key}, f)
    return public_key, private_key


VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY = _get_or_create_vapid_keys()
VAPID_CLAIMS = {'sub': 'mailto:admin@thehustlegame.co.uk'}

# Push layer for instant notifications (DMs, crew invites, attacks) instead
# of waiting on the client's poll interval. async_mode='threading' avoids
# eventlet/gevent monkey-patching (which is finicky with sqlite3) - the
# tradeoff is this only broadcasts correctly within a single worker
# process, so deployment must run gunicorn with -w 1 (see systemd unit).
# manage_session=False: Flask-SocketIO's own session-copy mechanism (for
# writing to flask.session from within socket handlers) is broken on
# Flask 3.1+ (RequestContext.session became a read-only property). Not
# needed here anyway - the connect handler only reads session['user_id'].
socketio = SocketIO(app, async_mode='threading', manage_session=False)

# Presence tracking for the Leaderboard's online indicator. Keyed by engine.io
# sid so a disconnect (which has no session/cookies available) can still be
# tied back to a user_id; counted per-user (not just a set) so multiple open
# tabs don't flip someone offline the moment one of them closes. In-memory
# only - safe because Socket.IO room broadcasts already require a single
# worker process (see note above), so there's only ever one copy of this.
_sid_to_user = {}
_online_counts = {}


@socketio.on('connect')
def handle_socket_connect():
    if 'user_id' not in session:
        return False
    uid = session['user_id']
    _sid_to_user[request.sid] = uid
    _online_counts[uid] = _online_counts.get(uid, 0) + 1
    join_room(str(uid))


@socketio.on('disconnect')
def handle_socket_disconnect():
    uid = _sid_to_user.pop(request.sid, None)
    if uid is not None:
        remaining = _online_counts.get(uid, 1) - 1
        if remaining <= 0:
            _online_counts.pop(uid, None)
        else:
            _online_counts[uid] = remaining


def is_user_online(user_id):
    return user_id in _online_counts


def notify_user(user_id, event, payload):
    """Fire-and-forget push to a specific user's room, if they're connected.
    Silently does nothing for offline users - they'll pick up the change on
    their next poll or the next time they log in."""
    socketio.emit(event, payload, room=str(user_id))


def send_push_notification(user_id, title, body, url='/'):
    """Best-effort browser push (works even with the game closed/backgrounded,
    unlike notify_user's socket room above). Never raises - a dead
    subscription just gets pruned, and any other delivery failure is logged
    and skipped so it can never break the action that triggered it."""
    db = get_db()
    rows = db.execute(
        'SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?',
        (user_id,)
    ).fetchall()
    db.close()
    if not rows:
        return
    payload = json.dumps({'title': title, 'body': body, 'url': url})
    for row in rows:
        try:
            webpush(
                subscription_info={
                    'endpoint': row['endpoint'],
                    'keys': {'p256dh': row['p256dh'], 'auth': row['auth']},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=dict(VAPID_CLAIMS),
            )
        except WebPushException as e:
            status = getattr(e.response, 'status_code', None)
            if status in (404, 410):
                db2 = get_db()
                db2.execute('DELETE FROM push_subscriptions WHERE id = ?', (row['id'],))
                db2.commit()
                db2.close()
            else:
                logging.warning(f'Push failed for user {user_id}: {e}')
        except Exception as e:
            logging.warning(f'Push failed for user {user_id}: {e}')


# ---------------------------------------------------------------------------
# Static files - only the game page and image assets, never source/db files
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'pimp-empires.html')


@app.route('/<path:filename>')
def serve_asset(filename):
    ext = os.path.splitext(filename)[1].lower()
    if filename == 'pimp-empires.html' or ext in ASSET_EXTENSIONS:
        return send_from_directory(BASE_DIR, filename)
    abort(404)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            pimp_name TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    ''')

    # Single current-state row per user - the server is the source of truth.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_state (
            user_id INTEGER PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # Single shared row (id always 1) holding the bot roster - every human
    # player competes against and sees the exact same bots, instead of each
    # account generating its own private copy.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS world_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            state_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    ''')

    # Web Push subscriptions - one row per device/browser a user has opted
    # in on, since the same account can be subscribed from a phone and a
    # desktop at once. Endpoint is unique per browser install, so it also
    # doubles as a natural de-dupe key if the same device subscribes twice.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT UNIQUE NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    db.commit()
    db.close()


# Run at import time, not just under `python app.py`, so WSGI servers
# (gunicorn etc.) that import this module directly still get the schema.
init_db()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not logged in'}), 401
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    if 'user_id' not in session:
        return None
    db = get_db()
    user = db.execute('SELECT id, email, pimp_name FROM users WHERE id = ?',
                       (session['user_id'],)).fetchone()
    db.close()
    return dict(user) if user else None


def load_state(user_id, pimp_name=None):
    """Load a user's state, creating a fresh one if none exists yet, then
    run every time-based system forward to now."""
    db = get_db()
    row = db.execute('SELECT state_json FROM player_state WHERE user_id = ?',
                      (user_id,)).fetchone()
    db.close()

    if row:
        state = json.loads(row['state_json'])
    else:
        state = ge.default_state(pimp_name or 'Big Boss')
        save_state(user_id, state)

    ge.apply_catchup(state)
    return state


def save_state(user_id, state):
    db = get_db()
    now = ge.now_ms()
    db.execute('''
        INSERT INTO player_state (user_id, state_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
    ''', (user_id, json.dumps(state), now))
    db.commit()
    db.close()


def load_world():
    """Load the single shared world (the bot roster), creating it if this
    is the very first request the server's ever handled, then run its
    time-based systems (bot growth, hospital recovery) forward to now."""
    db = get_db()
    row = db.execute('SELECT state_json FROM world_state WHERE id = 1').fetchone()
    db.close()

    if row:
        world = json.loads(row['state_json'])
    else:
        world = {}
        save_world(world)

    ge.apply_world_catchup(world)
    return world


def save_world(world):
    db = get_db()
    now = ge.now_ms()
    db.execute('''
        INSERT INTO world_state (id, state_json, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
    ''', (json.dumps(world), now))
    db.commit()
    db.close()


def build_human_targets(exclude_user_id):
    """Every other registered player, shaped to look like a bot so the
    existing bot-oriented UI (Attacks page, city listings, Leaderboard)
    can show and target real players with no client changes."""
    db = get_db()
    rows = db.execute('''
        SELECT p.user_id, p.state_json, u.pimp_name
        FROM player_state p JOIN users u ON u.id = p.user_id
        WHERE p.user_id != ?
    ''', (exclude_user_id,)).fetchall()
    db.close()

    humans = []
    for row in rows:
        try:
            s = json.loads(row['state_json'])
        except (TypeError, ValueError):
            continue
        h = ge.human_as_bot(row['user_id'], row['pimp_name'], s)
        h['isOnline'] = is_user_online(row['user_id'])
        humans.append(h)
    return humans


def build_crew_roster(user_id, state, world):
    """Full crew roster (leader + every member, each with live stats).
    Only the crew LEADER's own state_json carries a complete crewMembers
    list - a member's own state only knows the crew's name and who leads
    it - so if the viewer is a member, this reconstructs the roster by
    loading the leader's saved state (and, transitively, every other human
    member's) rather than trusting the viewer's own (empty) copy."""
    if not state.get('gang'):
        return {'emblem': '', 'members': []}

    leader_id = state.get('crewLeaderUserId')
    if leader_id is None:
        leader_state, leader_user_id = state, user_id
    else:
        leader_state, leader_user_id = load_state(leader_id), leader_id

    def human_entry(member_user_id, member_state, is_leader):
        return {
            'botId': ge.HUMAN_ID_OFFSET + member_user_id,
            'name': member_state.get('name', ''),
            'isYou': member_user_id == user_id,
            'isLeader': is_leader,
            'hoes': member_state.get('hoes', 0),
            'thugs': member_state.get('thugs', 0),
            'cars': member_state.get('cadillacs', 0),
            'netWorth': ge.total_net_worth(member_state),
        }

    members = [human_entry(leader_user_id, leader_state, True)]
    for m in leader_state.get('crewMembers', []):
        bot_id = m['botId']
        if bot_id >= ge.HUMAN_ID_OFFSET:
            member_user_id = bot_id - ge.HUMAN_ID_OFFSET
            member_state = state if member_user_id == user_id else (leader_state if member_user_id == leader_user_id else load_state(member_user_id))
            members.append(human_entry(member_user_id, member_state, False))
        else:
            bot = next((b for b in world.get('bots', []) if b['id'] == bot_id), None)
            if not bot:
                continue
            members.append({
                'botId': bot_id,
                'name': bot['boss'],
                'isYou': False,
                'isLeader': False,
                'hoes': bot.get('hoes', 0),
                'thugs': bot.get('thugs', 0),
                'cars': bot.get('cadillacs', 0),
                'netWorth': ge.bot_net_worth(bot),
            })
    return {'emblem': leader_state.get('crewEmblem', ''), 'members': members}


def crew_protected_ids(user_id, state, world):
    """Bot/human IDs currently in the caller's own crew (leader or
    fellow member, never the caller themselves) - used to block
    attacking/bombing your own crew regardless of which side of the
    leader/member split the caller is on."""
    roster = build_crew_roster(user_id, state, world)
    return {m['botId'] for m in roster['members'] if not m['isYou']}


def attach_world_view(state, world, user_id):
    """Mutates `state` in place to carry the shared bots plus every other
    real player for display - call this AFTER state has been saved, since
    this merged view is never persisted back into the player's own row."""
    state['bots'] = world.get('bots', []) + build_human_targets(user_id)
    state['botCrewEmblems'] = world.get('botCrewEmblems', {})
    state['globalAttackLog'] = world.get('globalAttackLog', [])
    state['worldRecords'] = world.get('records', {})
    state['selfProfileId'] = ge.HUMAN_ID_OFFSET + user_id
    state['crewRoster'] = build_crew_roster(user_id, state, world)
    state['rankInfo'] = ge.rank_info(state.get('xp', 0))

    # Leaderboard-position achievements need visibility into every other
    # player's net worth, which only exists once state['bots'] is built
    # above - can't be checked in apply_catchup like the other milestone
    # achievements. This runs after the caller already saved state, so
    # re-save if a new one actually unlocks.
    player_nw = ge.total_net_worth(state)
    better_count = sum(1 for b in state['bots'] if ge.bot_net_worth(b) > player_nw)
    global_rank = better_count + 1
    unlocked = False
    if global_rank == 1 and ge.award_achievement(state, 'top_of_the_charts'):
        unlocked = True
    if global_rank <= 10 and ge.award_achievement(state, 'top_ten'):
        unlocked = True

    # Hall of Fame leader badges - holds the #1 spot for a lifetime stat
    # (thugs killed / money stolen / factories destroyed) against everyone
    # else currently visible in the world. Sticks forever once earned, even
    # if someone else takes the top spot later - same "recompute, don't
    # revoke" rule as the other leaderboard-position badges above.
    def _leads(stat_key):
        val = state.get(stat_key, 0)
        return val > 0 and not any(b.get(stat_key, 0) > val for b in state['bots'])

    if _leads('statsThugsKilled') and ge.award_achievement(state, 'most_thugs_killed'):
        unlocked = True
    if _leads('statsMoneyStolen') and ge.award_achievement(state, 'most_money_stolen'):
        unlocked = True
    if _leads('statsFactoriesDestroyed') and ge.award_achievement(state, 'most_factories_destroyed'):
        unlocked = True

    if unlocked:
        save_state(user_id, state)

    return state


def action_response(user_id, state, world, extra=None):
    save_state(user_id, state)
    save_world(world)
    attach_world_view(state, world, user_id)
    payload = {'success': True, 'state': state}
    if extra:
        payload.update(extra)
    return jsonify(payload)


def handle_action(fn, *args, needs_world=False, **kwargs):
    """Run a game_engine action, translating GameError into a 400 response.
    The world (shared bots) is always loaded, since every response carries
    a fresh `state.bots` regardless of which action ran - pass
    needs_world=True when `fn` itself also needs it as its last argument
    (e.g. actions that look bots up, like inviting one to your crew)."""
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if needs_world:
            result = fn(state, *args, world, **kwargs)
        else:
            result = fn(state, *args, **kwargs)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '')
    pimp_name = data.get('pimpName', '').strip()

    if not email or not password or not pimp_name:
        return jsonify({'error': 'All fields required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if len(pimp_name) < 3 or len(pimp_name) > 20:
        return jsonify({'error': 'Pimp Name must be 3-20 characters'}), 400
    if '@' not in email or '.' not in email:
        return jsonify({'error': 'Invalid email address'}), 400

    try:
        db = get_db()
        cursor = db.cursor()

        cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
        if cursor.fetchone():
            db.close()
            return jsonify({'error': 'Email already registered'}), 409

        cursor.execute('SELECT id FROM users WHERE pimp_name = ?', (pimp_name,))
        if cursor.fetchone():
            db.close()
            return jsonify({'error': 'Pimp Name already taken'}), 409

        now = ge.now_ms()
        hashed_password = generate_password_hash(password)

        cursor.execute('''
            INSERT INTO users (email, password, pimp_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (email, hashed_password, pimp_name, now, now))
        db.commit()
        user_id = cursor.lastrowid
        db.close()

        session['user_id'] = user_id

        state = ge.default_state(pimp_name)
        ge.apply_catchup(state)
        save_state(user_id, state)
        world = load_world()
        attach_world_view(state, world, user_id)

        return jsonify({
            'success': True,
            'message': 'Account created successfully',
            'user': {'id': user_id, 'email': email, 'pimpName': pimp_name},
            'state': state,
        }), 201

    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    try:
        db = get_db()
        user = db.execute('SELECT id, email, pimp_name, password FROM users WHERE email = ?',
                           (email,)).fetchone()
        db.close()

        if not user:
            return jsonify({'error': 'Email not found'}), 404
        if not check_password_hash(user['password'], password):
            return jsonify({'error': 'Incorrect password'}), 401

        session['user_id'] = user['id']
        state = load_state(user['id'], user['pimp_name'])
        save_state(user['id'], state)
        world = load_world()
        save_world(world)
        attach_world_view(state, world, user['id'])

        return jsonify({
            'success': True,
            'message': 'Logged in successfully',
            'user': {'id': user['id'], 'email': user['email'], 'pimpName': user['pimp_name']},
            'state': state,
        })

    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500


@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'success': True, 'message': 'Logged out successfully'})


@app.route('/api/me', methods=['GET'])
def me():
    user = get_current_user()
    if not user:
        return jsonify({'loggedIn': False})
    return jsonify({'loggedIn': True, 'user': {
        'id': user['id'], 'email': user['email'], 'pimpName': user['pimp_name']
    }})


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@app.route('/api/state', methods=['GET'])
@login_required
def get_state():
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    save_state(user['id'], state)
    world = load_world()
    save_world(world)
    attach_world_view(state, world, user['id'])
    return jsonify({'success': True, 'state': state})


# ---------------------------------------------------------------------------
# Core economy
# ---------------------------------------------------------------------------

@app.route('/api/work', methods=['POST'])
@login_required
def api_work():
    data = request.get_json() or {}
    turns = int(data.get('turns', 0))
    return handle_action(ge.work_block, turns)


@app.route('/api/work/location', methods=['POST'])
@login_required
def api_work_location():
    data = request.get_json() or {}
    return handle_action(ge.set_work_location, data.get('location', ''))


@app.route('/api/bank/deposit', methods=['POST'])
@login_required
def api_bank_deposit():
    data = request.get_json() or {}
    amt = int(data.get('amount', 0))
    return handle_action(ge.bank_cash, amt)


@app.route('/api/bank/withdraw', methods=['POST'])
@login_required
def api_bank_withdraw():
    data = request.get_json() or {}
    amt = int(data.get('amount', 0))
    return handle_action(ge.withdraw_cash, amt)


@app.route('/api/factory/buy', methods=['POST'])
@login_required
def api_factory_buy():
    data = request.get_json() or {}
    return handle_action(ge.buy_factory, data.get('type', ''), data.get('qty', 1))


@app.route('/api/factory/sell', methods=['POST'])
@login_required
def api_factory_sell():
    data = request.get_json() or {}
    return handle_action(ge.sell_factory, data.get('type', ''), data.get('qty', 1))


@app.route('/api/factory/carratio', methods=['POST'])
@login_required
def api_factory_carratio():
    data = request.get_json() or {}
    return handle_action(ge.set_car_factory_ratio, data.get('ratio', 100))


@app.route('/api/factory/gunratio', methods=['POST'])
@login_required
def api_factory_gunratio():
    data = request.get_json() or {}
    return handle_action(ge.set_gun_factory_ratio, data.get('ratio', 0))


@app.route('/api/cadillacs/sellall', methods=['POST'])
@login_required
def api_cadillacs_sellall():
    return handle_action(ge.sell_all_cadillacs)


@app.route('/api/meds/sellall', methods=['POST'])
@login_required
def api_meds_sellall():
    return handle_action(ge.sell_all_meds)


@app.route('/api/cocaine/sellall', methods=['POST'])
@login_required
def api_cocaine_sellall():
    return handle_action(ge.sell_all_cocaine)


@app.route('/api/cocaine/sellall/overseas', methods=['POST'])
@login_required
def api_cocaine_sellall_overseas():
    return handle_action(ge.sell_cocaine_overseas)


@app.route('/api/trucks/sellall', methods=['POST'])
@login_required
def api_trucks_sellall():
    return handle_action(ge.sell_all_armored_trucks)


@app.route('/api/guns/sellall', methods=['POST'])
@login_required
def api_guns_sellall():
    data = request.get_json() or {}
    return handle_action(ge.sell_all_guns, data.get('type', ''))


@app.route('/api/blackmarket/buy', methods=['POST'])
@login_required
def api_bm_buy():
    data = request.get_json() or {}
    key = data.get('key', '')
    qty = int(data.get('qty', 1))
    return handle_action(ge.buy_black_market_item, key, qty)


@app.route('/api/blackmarket/sell', methods=['POST'])
@login_required
def api_bm_sell():
    data = request.get_json() or {}
    key = data.get('key', '')
    qty = int(data.get('qty', 1))
    return handle_action(ge.sell_black_market, key, qty)


@app.route('/api/drugs/buy', methods=['POST'])
@login_required
def api_drugs_buy():
    data = request.get_json() or {}
    drug_id = data.get('drugId', '')
    qty = int(data.get('qty', 1))
    return handle_action(ge.buy_drugs, drug_id, qty)


@app.route('/api/drugs/sell', methods=['POST'])
@login_required
def api_drugs_sell():
    data = request.get_json() or {}
    drug_id = data.get('drugId', '')
    qty = int(data.get('qty', 1))
    return handle_action(ge.sell_drugs, drug_id, qty)


# ---------------------------------------------------------------------------
# Heists / bribes / attacks
# ---------------------------------------------------------------------------

@app.route('/api/heist', methods=['POST'])
@login_required
def api_heist():
    data = request.get_json() or {}
    return handle_action(ge.run_heist, data.get('jobId', ''))


@app.route('/api/heist/casino', methods=['POST'])
@login_required
def api_heist_casino():
    return handle_action(ge.run_casino_heist, needs_world=True)


@app.route('/api/bribe', methods=['POST'])
@login_required
def api_bribe():
    return handle_action(ge.bribe_cops)


@app.route('/api/slots', methods=['POST'])
@login_required
def api_slots():
    data = request.get_json() or {}
    return handle_action(ge.play_slots, data.get('tier', ''))


@app.route('/api/attack', methods=['POST'])
@login_required
def api_attack():
    data = request.get_json() or {}
    target_id = data.get('botId')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if target_id in crew_protected_ids(user['id'], state, world):
            raise ge.GameError("You can't attack your own crew")
        if target_id is not None and target_id >= ge.HUMAN_ID_OFFSET:
            defender_id = target_id - ge.HUMAN_ID_OFFSET
            if defender_id == user['id']:
                raise ge.GameError("You can't attack yourself")
            defender_state = load_state(defender_id)
            result = ge.fight_human(state, defender_state, world, defender_target_id=target_id)
            save_state(defender_id, defender_state)
            attack_text = f"{state['name']} just hit you for £{result.get('cashWon', 0)}!" if result.get('won') else f"{state['name']} tried to hit you and failed."
            notify_user(defender_id, 'attacked', {'text': attack_text})
            send_push_notification(defender_id, "You're under attack!", attack_text)
        else:
            result = ge.fight_bot(state, target_id, world)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


@app.route('/api/bomb', methods=['POST'])
@login_required
def api_bomb():
    data = request.get_json() or {}
    target_id = data.get('botId')
    factory_type = data.get('factoryType')
    try:
        qty = int(data['qty']) if data.get('qty') is not None else None
    except (TypeError, ValueError):
        qty = None
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if target_id in crew_protected_ids(user['id'], state, world):
            raise ge.GameError("You can't bomb your own crew")
        if target_id is not None and target_id >= ge.HUMAN_ID_OFFSET:
            defender_id = target_id - ge.HUMAN_ID_OFFSET
            if defender_id == user['id']:
                raise ge.GameError("You can't bomb yourself")
            defender_state = load_state(defender_id)
            result = ge.bomb_human(state, defender_state, factory_type, qty)
            save_state(defender_id, defender_state)
            if result['destroyed'] > 0:
                bomb_text = f"{state['name']} just bombed your {factory_type} factories!"
                notify_user(defender_id, 'attacked', {'text': bomb_text})
                send_push_notification(defender_id, "You're under attack!", bomb_text)
        else:
            result = ge.bomb_bot(state, target_id, factory_type, world, qty)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


@app.route('/api/informer', methods=['POST'])
@login_required
def api_informer():
    data = request.get_json() or {}
    target_id = data.get('targetId')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if target_id is None:
            raise ge.GameError("No target selected")
        if target_id >= ge.HUMAN_ID_OFFSET:
            defender_id = target_id - ge.HUMAN_ID_OFFSET
            if defender_id == user['id']:
                raise ge.GameError("You already know what you've got")
            defender_state = load_state(defender_id)
            result = ge.informer_report_human(state, defender_state)
            save_state(defender_id, defender_state)
        else:
            result = ge.informer_report_bot(state, target_id, world)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


@app.route('/api/profile/<int:target_id>', methods=['GET'])
@login_required
def api_profile(target_id):
    """Public profile for a real player - name, crew, net worth, rank, and
    join date only. No combat stats here; that's still what the Informer
    fee is for. Bots don't have accounts/profiles, so only human IDs
    (target_id >= HUMAN_ID_OFFSET) resolve."""
    if target_id < ge.HUMAN_ID_OFFSET:
        return jsonify({'error': 'No profile for this target'}), 404
    target_user_id = target_id - ge.HUMAN_ID_OFFSET

    db = get_db()
    row = db.execute('SELECT id, pimp_name, created_at FROM users WHERE id = ?', (target_user_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'Player not found'}), 404

    target_state = load_state(target_user_id, row['pimp_name'])
    save_state(target_user_id, target_state)
    is_self = target_user_id == session['user_id']

    return jsonify({
        'success': True,
        'profile': {
            'botId': target_id,
            'name': row['pimp_name'],
            'gang': target_state.get('gang', ''),
            'emblem': target_state.get('crewEmblem', ''),
            'netWorth': ge.total_net_worth(target_state),
            'joinDate': row['created_at'],
            'rank': ge.rank_info(target_state.get('xp', 0)),
            'achievements': target_state.get('achievements', []),
            'isSelf': is_self,
            # Who's been hitting you is private - only ever sent back on your own profile.
            'lastAttackedBy': target_state.get('lastAttackedBy') if is_self else None,
        },
    })


# ---------------------------------------------------------------------------
# Hoes / crew / travel / settings
# ---------------------------------------------------------------------------

@app.route('/api/crew/name', methods=['POST'])
@login_required
def api_crew_name():
    data = request.get_json() or {}
    return handle_action(ge.save_crew_name, data.get('name', ''))


@app.route('/api/crew/emblem', methods=['POST'])
@login_required
def api_crew_emblem():
    data = request.get_json() or {}
    return handle_action(ge.set_crew_emblem, data.get('emblem', ''), needs_world=True)


@app.route('/api/crew/invite', methods=['POST'])
@login_required
def api_crew_invite():
    data = request.get_json() or {}
    target_id = data.get('botId')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if target_id is not None and target_id >= ge.HUMAN_ID_OFFSET:
            defender_id = target_id - ge.HUMAN_ID_OFFSET
            if defender_id == user['id']:
                raise ge.GameError("You can't invite yourself")
            defender_state = load_state(defender_id)
            result = ge.send_crew_invite_to_human(state, user['id'], defender_state, defender_id)
            save_state(defender_id, defender_state)
            notify_user(defender_id, 'dm', {'text': f"{state['name']} invited you to join their crew!"})
        else:
            result = ge.invite_to_crew(state, target_id, world)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


@app.route('/api/crew/invite/accept', methods=['POST'])
@login_required
def api_crew_invite_accept():
    data = request.get_json() or {}
    from_user_id = data.get('fromUserId')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        inviter_state = load_state(from_user_id)
        result = ge.accept_crew_invite(state, user['id'], inviter_state, from_user_id)
        save_state(from_user_id, inviter_state)
        notify_user(from_user_id, 'dm', {'text': f"{state['name']} joined your crew!"})
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


@app.route('/api/crew/invite/decline', methods=['POST'])
@login_required
def api_crew_invite_decline():
    data = request.get_json() or {}
    from_user_id = data.get('fromUserId')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        inviter_state = load_state(from_user_id)
        result = ge.decline_crew_invite(state, user['id'], inviter_state, from_user_id)
        save_state(from_user_id, inviter_state)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


@app.route('/api/crew/remove', methods=['POST'])
@login_required
def api_crew_remove():
    data = request.get_json() or {}
    bot_id = data.get('botId')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if bot_id is not None and bot_id >= ge.HUMAN_ID_OFFSET:
            member_id = bot_id - ge.HUMAN_ID_OFFSET
            member_state = load_state(member_id)
            ge.remove_from_crew(state, bot_id, member_state=member_state)
            save_state(member_id, member_state)
        else:
            ge.remove_from_crew(state, bot_id)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world)


@app.route('/api/travel', methods=['POST'])
@login_required
def api_travel():
    data = request.get_json() or {}
    return handle_action(ge.travel_to, data.get('city', ''))


@app.route('/api/settings/pimpname', methods=['POST'])
@login_required
def api_settings_pimpname():
    data = request.get_json() or {}
    return handle_action(ge.save_pimp_name, data.get('name', ''))


@app.route('/api/settings/tutorial', methods=['POST'])
@login_required
def api_settings_tutorial():
    data = request.get_json() or {}
    return handle_action(ge.set_tutorial_visibility, bool(data.get('enabled', True)))


@app.route('/api/settings/reset', methods=['POST'])
@login_required
def api_settings_reset():
    user = get_current_user()
    state = ge.default_state(user['pimp_name'])
    ge.apply_catchup(state)
    world = load_world()
    return action_response(user['id'], state, world)


@app.route('/api/turns/buy', methods=['POST'])
@login_required
def api_turns_buy():
    return handle_action(ge.buy_turns_with_real_money)


@app.route('/api/push/vapid-public-key', methods=['GET'])
def api_push_vapid_public_key():
    return jsonify({'publicKey': VAPID_PUBLIC_KEY})


@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def api_push_subscribe():
    data = request.get_json() or {}
    endpoint = data.get('endpoint')
    keys = data.get('keys') or {}
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    if not endpoint or not p256dh or not auth:
        return jsonify({'error': 'Invalid subscription'}), 400
    user = get_current_user()
    db = get_db()
    db.execute('''
        INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh, auth = excluded.auth
    ''', (user['id'], endpoint, p256dh, auth, ge.now_ms()))
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/push/unsubscribe', methods=['POST'])
@login_required
def api_push_unsubscribe():
    data = request.get_json() or {}
    endpoint = data.get('endpoint')
    user = get_current_user()
    db = get_db()
    db.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?', (user['id'], endpoint))
    db.commit()
    db.close()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Leaderboard / DMs (read mostly, plus canned bot replies)
# ---------------------------------------------------------------------------

@app.route('/api/leaderboard', methods=['GET'])
@login_required
def api_leaderboard():
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    save_state(user['id'], state)
    world = load_world()
    save_world(world)
    return jsonify({'success': True, 'leaderboard': ge.leaderboard(state, world)})


@app.route('/api/dm/send', methods=['POST'])
@login_required
def api_dm_send():
    data = request.get_json() or {}
    to_id = data.get('toId')
    text = data.get('text', '')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if to_id is not None and to_id >= ge.HUMAN_ID_OFFSET:
            defender_id = to_id - ge.HUMAN_ID_OFFSET
            if defender_id == user['id']:
                raise ge.GameError("You can't message yourself")
            defender_state = load_state(defender_id)
            result = ge.send_dm(state, to_id, text, world, defender_state=defender_state, sender_user_id=user['id'])
            save_state(defender_id, defender_state)
            notify_user(defender_id, 'dm', {'text': f"New message from {state['name']}"})
        else:
            result = ge.send_dm(state, to_id, text, world)
    except ge.GameError as e:
        return jsonify({'error': str(e)}), 400
    return action_response(user['id'], state, world, {'result': result})


@app.route('/api/dm/read', methods=['POST'])
@login_required
def api_dm_read():
    data = request.get_json() or {}
    from_id = data.get('fromId')
    return handle_action(ge.mark_dm_read, from_id)


if __name__ == '__main__':
    init_db()
    print('Pimp Empires server running on http://localhost:5000')
    print('SQLite database:', DB_PATH)
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)
