# setup_database.py
from app import app, db, UserData
from werkzeug.security import generate_password_hash

with app.app_context():
    # Drop and recreate all tables
    db.drop_all()
    db.create_all()
    print("✅ Database tables recreated")

    # Insert default admin user
    admin = UserData(
        username="admin",
        password_hash=generate_password_hash("admin123"),
        email="admin@example.com",
        is_active=True,
    )
    db.session.add(admin)
    db.session.commit()
    print("👤 Default admin user created (username=admin, password=admin123)")
