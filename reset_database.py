import os
import sys
from datetime import datetime, timezone

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def reset_database():
    print("🔄 Initializing database...")
    
    try:
        from app import create_app, db, UserData, License, ExtractionSession, ExtractedData
        from werkzeug.security import generate_password_hash
        
        # Create app instance
        app = create_app()
        
        with app.app_context():
            # Drop all tables
            db.drop_all()
            print("✅ Dropped all existing tables")
            
            # Create all tables
            db.create_all()
            print("✅ Created all database tables")
            
            # Create default admin user
            ADMIN_USERNAME = "Admin"
            ADMIN_PASSWORD_HASH = generate_password_hash("112122")
            
            admin_user = UserData(
                username=ADMIN_USERNAME,
                password_hash=ADMIN_PASSWORD_HASH,
                email="admin@example.com",
                is_admin=True,
                created_at=datetime.now(timezone.utc)
            )
            
            db.session.add(admin_user)
            db.session.commit()
            print("✅ Created default admin user")
            
            # Create a sample license
            from datetime import timedelta
            sample_license = License(
                key="DEMO1234",
                expiry=datetime.now(timezone.utc) + timedelta(days=30),
                max_usage=1000,
                created_at=datetime.now(timezone.utc)
            )
            
            db.session.add(sample_license)
            db.session.commit()
            print("✅ Created sample license: DEMO1234")
            
            print("✅ Database reset completed successfully!")
            print(f"📋 Admin credentials - Username: {ADMIN_USERNAME}, Password: 112122")
            print("🔑 Sample license key: DEMO1234")
            
    except Exception as e:
        print(f"❌ Database reset failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    if reset_database():
        print("🎉 Database reset completed!")
    else:
        print("💥 Database reset failed!")
        sys.exit(1)