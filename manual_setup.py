# manual_setup.py
from app import app, db, UserData, License
from datetime import datetime, timedelta

with app.app_context():
    # Create tables
    db.create_all()
    
    # Create default admin user if not exists
    if not UserData.query.filter_by(username='admin').first():
        from werkzeug.security import generate_password_hash
        admin = UserData(
            username='admin',
            password_hash=generate_password_hash('12345'),
            created_at=datetime.utcnow()
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Default admin user created (username: admin, password: 12345)")
    
    print("✅ Database setup completed!")