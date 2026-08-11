import sqlite3
import json
import sys

def rename_player(db_path, old_name, new_name):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Check if new name exists
    if conn.execute('SELECT 1 FROM users WHERE pimp_name = ? COLLATE NOCASE', (new_name,)).fetchone():
        print(f"Error: {new_name} already exists!")
        return

    # Find old user
    user = conn.execute('SELECT id, pimp_name FROM users WHERE pimp_name = ? COLLATE NOCASE', (old_name,)).fetchone()
    if not user:
        print(f"Error: Player {old_name} not found in database!")
        return
        
    user_id = user['id']
    actual_old_name = user['pimp_name']
    
    print(f"Found {actual_old_name} with ID {user_id}. Renaming to {new_name}...")
    
    # 1. Update users table
    conn.execute('UPDATE users SET pimp_name = ? WHERE id = ?', (new_name, user_id))
    
    # 2. Update their own player_state
    state_row = conn.execute('SELECT state_json FROM player_state WHERE user_id = ?', (user_id,)).fetchone()
    if state_row:
        state = json.loads(state_row['state_json'])
        state['name'] = new_name
        # If they are their own crew leader, update it too
        if state.get('crewLeaderName') == actual_old_name:
            state['crewLeaderName'] = new_name
            
        conn.execute('UPDATE player_state SET state_json = ? WHERE user_id = ?', (json.dumps(state), user_id))

    # 3. Update all other player_states that might reference them
    all_states = conn.execute('SELECT user_id, state_json FROM player_state').fetchall()
    for row in all_states:
        uid = row['user_id']
        if uid == user_id:
            continue
            
        st = json.loads(row['state_json'])
        changed = False
        
        # Check crewLeaderName
        if st.get('crewLeaderName') == actual_old_name:
            st['crewLeaderName'] = new_name
            changed = True
            
        # Check crewMembers
        if 'crewMembers' in st:
            for member in st['crewMembers']:
                if member.get('boss') == actual_old_name:
                    member['boss'] = new_name
                    changed = True
                    
        # Check pendingCrewInvites
        if 'pendingCrewInvites' in st:
            for inv in st['pendingCrewInvites']:
                if inv.get('fromName') == actual_old_name:
                    inv['fromName'] = new_name
                    changed = True
                    
        # theJob
        if 'theJob' in st and st['theJob']:
            job = st['theJob']
            if job.get('starterName') == actual_old_name:
                job['starterName'] = new_name
                changed = True
            if 'roles' in job:
                for role in job['roles'].values():
                    if role and role.get('name') == actual_old_name:
                        role['name'] = new_name
                        changed = True
                        
        if changed:
            conn.execute('UPDATE player_state SET state_json = ? WHERE user_id = ?', (json.dumps(st), uid))
            
    conn.commit()
    conn.close()
    print("Successfully renamed!")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python rename_player.py <game.db path> <old_name> <new_name>")
        sys.exit(1)
    
    rename_player(sys.argv[1], sys.argv[2], sys.argv[3])
