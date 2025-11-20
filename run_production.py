# run_production.py
from waitress import serve
from app import app
import os

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Production Server on port {port}")
    print(f"Admin login: http://localhost:{port}/admin/login")
    print("Username: Admin, Password: 112122")
    
    # Use Waitress for production on Windows
    serve(app, host='0.0.0.0', port=port)