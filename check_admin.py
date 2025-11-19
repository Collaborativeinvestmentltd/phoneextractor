# check_admin.py
from app import app, db, UserData
from werkzeug.security import generate_password_hash

with app.app_context():
    # Check if admin user exists
    admin = UserData.query.filter_by(username='admin').first()
    if not admin:
        print("❌ No admin user found. Creating one...")
        admin = UserData(
            username='admin',
            password_hash=generate_password_hash('12345'),
            created_at=db.func.now()
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin user created: username='admin', password='12345'")
    else:
        print("✅ Admin user exists")
    
    # Check licenses
    from app import License
    licenses = License.query.all()
    print(f"✅ {len(licenses)} licenses in database")