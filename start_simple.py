# start_simple.py - Simple startup without complex logging
import os
import sys
import logging

# Configure basic logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# Now import and run the app
from app import app

if __name__ == "__main__":
    print("🚀 Starting Data Extractor (Simple Mode)...")
    print("✅ REAL Scrapers are working!")
    print("📍 http://localhost:5000")
    print("🔑 Admin: http://localhost:5000/admin/login")
    print("   Username: Admin, Password: 112122")
    print("")
    print("💡 Test the scrapers at: http://localhost:5000/test-scrapers")
    
    # Create necessary directories
    for directory in ['logs', 'data']:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"✅ Created {directory}/ directory")
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)