# migrations.py - Database migration script
import os
import sys
from sqlalchemy import text

def migrate_database():
    """Apply database migrations for schema changes"""
    from app import db, app
    
    with app.app_context():
        try:
            # Check if is_admin column exists in user_data table
            result = db.session.execute(text("PRAGMA table_info(user_data)"))
            columns = [row[1] for row in result]
            
            if 'is_admin' not in columns:
                print("Adding is_admin column to user_data table...")
                db.session.execute(text("ALTER TABLE user_data ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
                db.session.commit()
                print("✅ Added is_admin column")
            
            # Check license table columns
            result = db.session.execute(text("PRAGMA table_info(license)"))
            columns = [row[1] for row in result]
            
            if 'max_usage' not in columns:
                print("Adding max_usage column to license table...")
                db.session.execute(text("ALTER TABLE license ADD COLUMN max_usage INTEGER DEFAULT 1000"))
                db.session.commit()
                print("✅ Added max_usage column")
            
            if 'usage_count' not in columns:
                print("Adding usage_count column to license table...")
                db.session.execute(text("ALTER TABLE license ADD COLUMN usage_count INTEGER DEFAULT 0"))
                db.session.commit()
                print("✅ Added usage_count column")
            
            if 'last_used' not in columns:
                print("Adding last_used column to license table...")
                db.session.execute(text("ALTER TABLE license ADD COLUMN last_used DATETIME"))
                db.session.commit()
                print("✅ Added last_used column")
            
            if 'revoked' not in columns:
                print("Adding revoked column to license table...")
                db.session.execute(text("ALTER TABLE license ADD COLUMN revoked BOOLEAN DEFAULT FALSE"))
                db.session.commit()
                print("✅ Added revoked column")
            
            # Check user_data table for other missing columns
            result = db.session.execute(text("PRAGMA table_info(user_data)"))
            columns = [row[1] for row in result]
            
            if 'is_active' not in columns:
                print("Adding is_active column to user_data table...")
                db.session.execute(text("ALTER TABLE user_data ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
                db.session.commit()
                print("✅ Added is_active column")
            
            print("✅ Database migration completed successfully!")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            db.session.rollback()
            # Try to recreate tables from scratch
            try:
                print("Attempting to recreate tables...")
                db.drop_all()
                db.create_all()
                print("✅ Tables recreated successfully")
            except Exception as e2:
                print(f"❌ Table recreation failed: {e2}")

if __name__ == "__main__":
    migrate_database()