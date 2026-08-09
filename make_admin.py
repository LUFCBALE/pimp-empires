import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game.db')

def make_admin(email):
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    
    user = cursor.execute('SELECT id, pimp_name, is_admin FROM users WHERE email = ?', (email,)).fetchone()
    if not user:
        print(f"Error: No user found with email {email}")
        db.close()
        return
        
    if user[2]:
        print(f"User {user[1]} ({email}) is already an admin.")
    else:
        cursor.execute('UPDATE users SET is_admin = 1 WHERE email = ?', (email,))
        db.commit()
        print(f"Success! User {user[1]} ({email}) has been granted admin privileges.")
        
    db.close()

if __name__ == '__main__':
    print("--- Admin Promotion Utility ---")
    email = input("Enter the email address of the account to make admin: ").strip()
    if email:
        make_admin(email)
    else:
        print("Canceled.")
