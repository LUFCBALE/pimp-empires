# ---------------------------------------------------------------------------
# Admin Dashboard
# ---------------------------------------------------------------------------

@app.route('/admin')
def admin_page():
    return send_from_directory(BASE_DIR, 'admin.html')

@app.route('/api/admin/stats', methods=['GET'])
@require_admin
def api_admin_stats():
    db = get_db()
    total_users = db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
    users = db.execute('SELECT state_json FROM player_state').fetchall()
    db.close()
    
    total_cash = 0
    total_net_worth = 0
    for u in users:
        try:
            st = json.loads(u['state_json'])
            total_cash += st.get('cash', 0)
            total_net_worth += st.get('lifetimeEarnings', 0)
        except:
            pass
            
    return jsonify({
        'totalUsers': total_users,
        'onlineUsers': len(_online_counts),
        'totalCash': total_cash,
        'totalEarnings': total_net_worth
    })

@app.route('/api/admin/users', methods=['GET'])
@require_admin
def api_admin_users():
    db = get_db()
    users = db.execute('''
        SELECT u.id, u.email, u.pimp_name, u.is_admin, u.is_banned, p.state_json 
        FROM users u 
        LEFT JOIN player_state p ON u.id = p.user_id
        ORDER BY u.id DESC
    ''').fetchall()
    db.close()
    
    result = []
    for u in users:
        st = {}
        if u['state_json']:
            try:
                st = json.loads(u['state_json'])
            except:
                pass
        result.append({
            'id': u['id'],
            'email': u['email'],
            'name': u['pimp_name'],
            'isAdmin': bool(u['is_admin']),
            'isBanned': bool(u['is_banned']),
            'cash': st.get('cash', 0),
            'turns': st.get('turns', 0),
            'rank': st.get('rank', 1),
            'state': st
        })
    return jsonify({'users': result})

@app.route('/api/admin/users/<int:target_id>/ban', methods=['POST'])
@require_admin
def api_admin_ban_user(target_id):
    db = get_db()
    user = db.execute('SELECT is_banned FROM users WHERE id = ?', (target_id,)).fetchone()
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    new_status = 0 if user['is_banned'] else 1
    db.execute('UPDATE users SET is_banned = ? WHERE id = ?', (new_status, target_id))
    db.commit()
    db.close()
    
    return jsonify({'success': True, 'isBanned': bool(new_status)})

@app.route('/api/admin/users/<int:target_id>/credit', methods=['POST'])
@require_admin
def api_admin_credit_user(target_id):
    data = request.get_json() or {}
    cash = int(data.get('cash', 0))
    turns = int(data.get('turns', 0))
    respect = int(data.get('respect', 0))
    
    state = load_state(target_id)
    if state is None:
        return jsonify({'error': 'State not found'}), 404
        
    if cash > 0:
        state['cash'] = state.get('cash', 0) + cash
        state['lifetimeEarnings'] = state.get('lifetimeEarnings', 0) + cash
    if turns > 0:
        state['turns'] = state.get('turns', 0) + turns
    if respect > 0:
        state['respect'] = state.get('respect', 0) + respect
        
    save_state(target_id, state)
    notify_user(target_id, 'update', state)
    return jsonify({'success': True, 'state': state})

@app.route('/api/admin/announce', methods=['POST'])
@require_admin
def api_admin_announce():
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'error': 'Message required'}), 400
        
    socketio.emit('announcement', {'message': message})
    
    db = get_db()
    users = db.execute('SELECT id FROM users').fetchall()
    db.close()
    
    for u in users:
        send_push_notification(u['id'], 'Server Announcement', message)
        
    return jsonify({'success': True})
