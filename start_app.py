# start_app.py
import os
import sys
import logging
from app import app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    print("🚀 Starting Data Extractor...")
    print("📍 http://localhost:5000")
    print("🔑 Admin: http://localhost:5000/admin/login")
    print("   Username: Admin, Password: 112122")
    
    # Create necessary directories
    for directory in ['logs', 'data']:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"✅ Created {directory}/ directory")
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    except Exception as e:
        print(f"❌ Error starting app: {e}")
        print("💡 Try running: python start_app.py")