# init_db.py
from app import app, db
import os

with app.app_context():
    # Create all tables
    db.create_all()
    print("Database initialized successfully!")
    
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
        print("Logs directory created!")