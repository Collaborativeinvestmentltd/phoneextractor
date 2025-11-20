# migrations.py - Manual database migration script
import sqlite3
import os
from datetime import datetime, timezone

def migrate_database():
    """Manual database migration for existing installations"""
    db_path = 'data.db'
    
    if not os.path.exists(db_path):
        print("No existing database found. Starting fresh.")
        return
    
    print("Migrating existing database...")
    
    # Connect to SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if new columns exist
        cursor.execute("PRAGMA table_info(user_data)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Add missing columns to user_data
        if 'is_admin' not in columns:
            print("Adding is_admin column to user_data...")
            cursor.execute("ALTER TABLE user_data ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
        
        # Create new tables if they don't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS extraction_session (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                license_key TEXT NOT NULL,
                keywords TEXT,
                location TEXT,
                platforms TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                status TEXT DEFAULT 'running',
                total_results INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES user_data (id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS extracted_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                business_name TEXT,
                address TEXT,
                source TEXT NOT NULL,
                extracted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_valid BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (session_id) REFERENCES extraction_session (id)
            )
        """)
        
        # Update admin user
        cursor.execute("UPDATE user_data SET is_admin = TRUE WHERE username = 'Admin'")
        
        # Add max_usage to license table if missing
        cursor.execute("PRAGMA table_info(license)")
        license_columns = [col[1] for col in cursor.fetchall()]
        if 'max_usage' not in license_columns:
            print("Adding max_usage column to license...")
            cursor.execute("ALTER TABLE license ADD COLUMN max_usage INTEGER DEFAULT 1000")
        
        conn.commit()
        print("✅ Database migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()