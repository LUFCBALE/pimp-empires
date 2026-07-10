# Flask Server Setup for Pimp Empires

## Quick Start

### Step 1: Install Flask
```bash
pip install -r requirements.txt
```

If `pip` is not found, try:
```bash
python -m pip install -r requirements.txt
```

### Step 2: Run the server
```bash
python app.py
```

You should see:
```
🎮 Pimp Empires server running on http://localhost:5000
📁 SQLite database: game.db
```

### Step 3: Open the game
Open your browser to:
```
http://localhost:5000/pimp-empires.html
```

## How It Works

**Backend (Flask):**
- `/api/signup` - Create account
- `/api/login` - Login user
- `/api/logout` - Logout
- `/api/save` - Save game state
- `/api/load` - Load game state

**Database:**
- SQLite file: `game.db` (created automatically)
- Tables: `users` and `game_saves`

## Requirements

- Python 3.7+
- Flask 2.3.0
- Werkzeug 2.3.0

## Troubleshooting

**"ModuleNotFoundError: No module named 'flask'"**
```bash
pip install Flask
```

**"Address already in use"** (port 5000 taken)
- Edit `app.py` and change `port=5000` to `port=5001`

**Windows - Python not found**
- Install Python from https://www.python.org/downloads/
- Check "Add Python to PATH" during installation
- Restart terminal after install

**Mac - Use python3 instead**
```bash
python3 app.py
pip3 install -r requirements.txt
```

## Development

The server runs in debug mode (auto-reloads on code changes). In production, use a production WSGI server like Gunicorn:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Data Storage

Game saves are stored in SQLite. Each user can have up to 5 saved game states (older saves are auto-deleted).

Password are hashed with werkzeug's `generate_password_hash()` using pbkdf2 with SHA256.

Enjoy your game!
