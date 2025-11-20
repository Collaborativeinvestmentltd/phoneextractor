# debug_app.py
import os
import sys
import logging
from app import app

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

def check_dependencies():
    print("🔍 Checking dependencies...")
    try:
        from flask import __version__ as flask_v
        print(f"✅ Flask: {flask_v}")
    except ImportError as e:
        print(f"❌ Flask: {e}")
    
    try:
        from flask_sqlalchemy import __version__ as sqla_v
        print(f"✅ Flask-SQLAlchemy: {sqla_v}")
    except ImportError as e:
        print(f"❌ Flask-SQLAlchemy: {e}")
    
    try:
        from playwright import __version__ as pw_v
        print(f"✅ Playwright: {pw_v}")
    except ImportError as e:
        print(f"❌ Playwright: {e}")

def check_config():
    print("\n🔍 Checking configuration...")
    print(f"✅ SECRET_KEY: {'Set' if app.config.get('SECRET_KEY') else 'Missing'}")
    print(f"✅ DATABASE_URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    print(f"✅ DEBUG: {app.config.get('DEBUG')}")

def check_database():
    print("\n🔍 Checking database...")
    try:
        with app.app_context():
            from app import db
            db.engine.connect()
            print("✅ Database connection: OK")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")

def check_routes():
    print("\n🔍 Checking routes...")
    with app.test_client() as client:
        try:
            response = client.get('/')
            print(f"✅ Home route: {response.status_code}")
        except Exception as e:
            print(f"❌ Home route failed: {e}")
        
        try:
            response = client.get('/health')
            print(f"✅ Health route: {response.status_code}")
        except Exception as e:
            print(f"❌ Health route failed: {e}")

if __name__ == "__main__":
    print("🚀 Starting debug...")
    check_dependencies()
    check_config()
    check_database()
    check_routes()
    print("\n🎯 Debug complete!")