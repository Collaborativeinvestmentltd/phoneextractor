# start.py
import os
from app import app

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    print(f"Starting Data Extractor on port {port}")
    print(f"Debug mode: {debug}")
    print(f"Admin login: http://localhost:{port}/admin/login")
    print("Username: Admin, Password: 112122")
    
    app.run(host='0.0.0.0', port=port, debug=debug)