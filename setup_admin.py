import os
from werkzeug.security import generate_password_hash
from app import app, db, UserData

with app.app_context():
    # Set proper environment variables
    os.environ['SECRET_KEY'] = 'calmdownokay'
    os.environ['CSRF_SECRET_KEY'] = '1234567890987654321'
    os.environ['ADMIN_USERNAME'] = 'admin'
    os.environ['ADMIN_PASSWORD_HASH'] = generate_password_hash('12345')
    
    print("✅ Admin setup complete")
    print(f"🔑 Username: admin")
    print(f"🔒 Password: 12345")
    print("⚠️  Change these credentials in production!")