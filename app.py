from flask import Flask, request, jsonify, session, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import json
import os
from functools import wraps

import game_engine as ge

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'game.db')
ASSET_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.mp3', '.ogg'}

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pimp-empires-secret-key-change-in-production')


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
        humans.append(ge.human_as_bot(row['user_id'], row['pimp_name'], s))
    return humans


def attach_world_view(state, world, user_id):
    """Mutates `state` in place to carry the shared bots plus every other
    real player for display - call this AFTER state has been saved, since
    this merged view is never persisted back into the player's own row."""
    state['bots'] = world.get('bots', []) + build_human_targets(user_id)
    state['botCrewEmblems'] = world.get('botCrewEmblems', {})
    state['globalAttackLog'] = world.get('globalAttackLog', [])
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


@app.route('/api/store/buy', methods=['POST'])
@login_required
def api_store_buy():
    data = request.get_json() or {}
    group = data.get('group', '')
    item_id = data.get('itemId', '')
    qty = int(data.get('qty', 1))
    return handle_action(ge.buy_store_item, group, item_id, qty)


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


@app.route('/api/attack', methods=['POST'])
@login_required
def api_attack():
    data = request.get_json() or {}
    target_id = data.get('botId')
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if target_id is not None and target_id >= ge.HUMAN_ID_OFFSET:
            defender_id = target_id - ge.HUMAN_ID_OFFSET
            if defender_id == user['id']:
                raise ge.GameError("You can't attack yourself")
            defender_state = load_state(defender_id)
            result = ge.fight_human(state, defender_state, world)
            save_state(defender_id, defender_state)
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
    user = get_current_user()
    state = load_state(user['id'], user['pimp_name'])
    world = load_world()
    try:
        if target_id is not None and target_id >= ge.HUMAN_ID_OFFSET:
            defender_id = target_id - ge.HUMAN_ID_OFFSET
            if defender_id == user['id']:
                raise ge.GameError("You can't bomb yourself")
            defender_state = load_state(defender_id)
            result = ge.bomb_human(state, defender_state, factory_type)
            save_state(defender_id, defender_state)
        else:
            result = ge.bomb_bot(state, target_id, factory_type, world)
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
    return handle_action(ge.remove_from_crew, data.get('botId'))


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


@app.route('/api/settings/reset', methods=['POST'])
@login_required
def api_settings_reset():
    user = get_current_user()
    state = ge.default_state(user['pimp_name'])
    world = load_world()
    return action_response(user['id'], state, world)


@app.route('/api/turns/buy', methods=['POST'])
@login_required
def api_turns_buy():
    return handle_action(ge.buy_turns_with_real_money)


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
    app.run(debug=True, port=5000)
