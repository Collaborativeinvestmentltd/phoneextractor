# run.py - Alternative entry point with better error handling
import os
import sys
from app import app, init_database

def main():
    """Main entry point with enhanced error handling"""
    try:
        # Initialize database
        with app.app_context():
            init_database()
        
        print("✅ Database initialized successfully")
        print("🚀 Starting Flask application...")
        
        debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
        port = int(os.environ.get('PORT', 5000))
        
        if os.environ.get('PRODUCTION'):
            print("[PRODUCTION] Starting production server with Waitress...")
            from waitress import serve
            serve(app, host='0.0.0.0', port=port)
        else:
            print("[DEVELOPMENT] Starting development server...")
            app.run(
                debug=debug_mode,
                host='0.0.0.0',
                port=port,
                use_reloader=False
            )
            
    except Exception as e:
        print(f"❌ Failed to start application: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()