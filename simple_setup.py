# simple_setup.py
from app import app, db

with app.app_context():
    db.create_all()
    print("✅ Database tables created!")
    print("✅ Application is ready to run!")
    print("🚀 Run: python app.py")