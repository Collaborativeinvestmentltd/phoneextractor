import logging
from flask import Response, jsonify, request
from flask import make_response
from flask import Flask, request, jsonify
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session, flash, stream_with_context
from functools import wraps
from threading import Thread, Lock, Event
from datetime import datetime, timedelta, timezone
import json, os, time, secrets
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

# Global extraction flags
EXTRACTING = False
EXTRACTION_THREAD = None
EXTRACTION_STOP_EVENT = Event()

# Storage for live extracted results
EXTRACTION_DATA = []
DATA_LOCK = Lock()

# Import CSRF with fallback
try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
    CSRF_AVAILABLE = True
except ImportError as e:
    print(f"CSRF not available: {e}")
    class CSRFProtect:
        def init_app(self, app):
            self._app = app
    def generate_csrf():
        return "dummy-csrf-token"
    CSRF_AVAILABLE = False

from flask_migrate import Migrate

# -----------------------
# Import scrapers
# -----------------------
SCRAPERS_AVAILABLE = False
scraper_functions = {}

try:
    from scrapers import (
        scrape_yellowpages, scrape_whitepages, scrape_manta,
        scrape_411, scrape_local_com,
        safe_scrape_yelp, safe_scrape_foursquare
    )
    
    scraper_functions = {
        'yellowpages': scrape_yellowpages,
        'whitepages': scrape_whitepages,
        'manta': scrape_manta,
        '411': scrape_411,
        'local_com': scrape_local_com,
        'yelp': safe_scrape_yelp,
        'foursquare': safe_scrape_foursquare
    }
    SCRAPERS_AVAILABLE = True
    print("[OK] Scrapers integrated successfully")
except ImportError as e:
    print(f"[WARN] Scrapers not available: {e}")
    SCRAPERS_AVAILABLE = False

# Mock scraper functions for deployment
def mock_scraper(keywords, location):
    time.sleep(2)  # Simulate scraping delay
    return [{
        'number': f"555-{int(time.time()) % 10000:04d}",
        'name': f'Sample Business {int(time.time()) % 1000}',
        'address': f'123 Main St, {location or "Sample City"}',
        'source': 'mock'
    }]

# Replace unavailable scrapers with mock functions
for platform in ['yellowpages', 'whitepages', 'manta', '411', 'local_com', 'yelp', 'foursquare']:
    if platform not in scraper_functions:
        scraper_functions[platform] = mock_scraper

# -----------------------
# Configuration
# -----------------------
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///data.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    EXTRACTION_TIMEOUT = 300
    WTF_CSRF_ENABLED = bool(CSRF_AVAILABLE)
    WTF_CSRF_SECRET_KEY = os.environ.get('CSRF_SECRET_KEY', secrets.token_hex(32))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_MAX_BYTES = 10 * 1024 * 1024
    LOG_BACKUP_COUNT = 5
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Session configurations
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'session:'

# -----------------------
# Initialize Extensions
# -----------------------
db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)

# -----------------------
# Database Models
# -----------------------
class UserData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    
    licenses = db.relationship('License', backref='user', lazy=True, cascade='all, delete-orphan')

class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_data.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expiry = db.Column(db.DateTime, nullable=True)
    revoked = db.Column(db.Boolean, default=False)
    last_used = db.Column(db.DateTime)
    usage_count = db.Column(db.Integer, default=0)
    
    def is_valid(self):
        if self.revoked:
            return False
        if self.expiry:
            if self.expiry.tzinfo is None:
                expiry_utc = self.expiry.replace(tzinfo=timezone.utc)
            else:
                expiry_utc = self.expiry.astimezone(timezone.utc)
            
            now_utc = datetime.now(timezone.utc)
            if expiry_utc < now_utc:
                return False
        return True

# -----------------------
# App Factory
# -----------------------
def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    
    # Configure logging
    configure_logging(app)
    
    # Add proxy fix for production
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # Session configuration
    @app.before_request
    def make_session_permanent():
        session.permanent = True
        app.permanent_session_lifetime = timedelta(hours=24)
    
    return app

def configure_logging(app):
    """Set up logging with rotation"""
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    class SafeFormatter(logging.Formatter):
        def format(self, record):
            if hasattr(record, 'msg') and isinstance(record.msg, str):
                record.msg = (record.msg
                    .replace('✅', '[OK]')
                    .replace('❌', '[ERROR]')
                    .replace('⚠️', '[WARN]')
                    .replace('🚀', '[START]'))
            return super().format(record)
    
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=app.config['LOG_MAX_BYTES'],
        backupCount=app.config['LOG_BACKUP_COUNT'],
        encoding='utf-8'
    )
    
    formatter = SafeFormatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, app.config['LOG_LEVEL']))
    
    logging.basicConfig(
        level=getattr(logging, app.config['LOG_LEVEL']),
        format='%(asctime)s %(levelname)s: %(message)s',
        handlers=[file_handler]
    )
    
    app.logger.addHandler(file_handler)
    app.logger.setLevel(getattr(logging, app.config['LOG_LEVEL']))
    app.logger.info('Application startup')

# Create app instance
app = create_app()

# Limiter init
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["10 per minute"]
)
limiter.init_app(app)

# -----------------------
# Global Variables
# -----------------------
EXTRACTION_DATA = []
DATA_LOCK = Lock()
EXTRACTION_THREAD = None
EXTRACTING = False
EXTRACTION_STOP_EVENT = Event()

# -----------------------
# Admin configuration - Fixed credentials
# -----------------------
ADMIN_USERNAME = "Admin"
ADMIN_PASSWORD_HASH = generate_password_hash("112122")

def verify_admin_password(password):
    """Verify admin password"""
    return check_password_hash(ADMIN_PASSWORD_HASH, password)

# -----------------------
# Authentication Decorators
# -----------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin access required", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function

def user_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_logged_in'):
            return jsonify({"error": "Authentication required"}), 403
        return f(*args, **kwargs)
    return decorated_function

# -----------------------
# Helper Functions
# -----------------------
def safe_log_info(message):
    """Safely log info messages without Unicode issues"""
    safe_message = (message
        .replace('✅', '[OK]')
        .replace('❌', '[ERROR]')
        .replace('⚠️', '[WARN]'))
    app.logger.info(safe_message)

def safe_log_error(message):
    """Safely log error messages without Unicode issues"""
    safe_message = (message
        .replace('✅', '[OK]')
        .replace('❌', '[ERROR]')
        .replace('⚠️', '[WARN]'))
    app.logger.error(safe_message)

# -----------------------
# Initialize Database
# -----------------------
with app.app_context():
    db.create_all()
    app.logger.info("Database tables created")

# -----------------------
# Scraper Integration
# -----------------------
def run_scraper(platform, keywords, location):
    """Run specific scraper based on platform."""
    if not SCRAPERS_AVAILABLE or platform not in scraper_functions:
        app.logger.warning(f"Scraper not available for platform: {platform}")
        return []

    # Allow empty keywords/location
    keywords = (keywords or '').strip()
    location = (location or '').strip()

    try:
        scraper_func = scraper_functions[platform]
        safe_log_info(f"Running scraper: {platform} for '{keywords or '<<no-keywords>>'}' in '{location or '<<no-location>>'}'")
        results = scraper_func(keywords, location)
        if not isinstance(results, list):
            safe_log_error(f"Scraper {platform} returned non-list result, coerced to [].")
            return []
        safe_log_info(f"[OK] Scraper {platform} returned {len(results)} results")
        return results
    except Exception as e:
        safe_log_error(f"[ERROR] Scraper {platform} failed: {str(e)}")
        return []

# -----------------------
# Routes with CSRF Protection
# -----------------------
@app.route("/")
def index():
    """Main application page"""
    countries, country_states = [], {}
    
    data_file = os.path.join("data", "countries_states.json")
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            country_states = {item["name"]: item.get("states", []) for item in data}
            countries = sorted(country_states.keys())
    except FileNotFoundError:
        app.logger.warning(f"Countries/states file not found: {data_file}")
        country_states = {}
        countries = []
    except Exception as e:
        app.logger.error(f"Error loading countries/states: {str(e)}")
        country_states = {}
        countries = []

    return render_template("index.html",
                           countries=countries,
                           states=[],
                           country_states=country_states,
                           numbers=EXTRACTION_DATA,
                           csrf_token=generate_csrf(),
                           SCRAPERS_AVAILABLE=SCRAPERS_AVAILABLE)

@limiter.limit("10/minute")
@app.route("/extract", methods=["POST"])
@user_login_required
def start_extraction():
    """Start extraction job."""
    global EXTRACTION_THREAD, EXTRACTING, EXTRACTION_DATA, EXTRACTION_STOP_EVENT

    # Prevent parallel jobs
    if EXTRACTING:
        return jsonify({"error": "Extraction already running"}), 400

    # Parse request
    content_type = (request.content_type or "").lower()

    if "application/json" in content_type:
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "Invalid JSON body"}), 415

        keywords = (body.get("keywords") or "").strip()
        location = (body.get("location") or "").strip()
        raw_platforms = body.get("platforms")
        if isinstance(raw_platforms, list):
            platforms = raw_platforms
        elif isinstance(raw_platforms, str):
            platforms = [raw_platforms]
        else:
            platforms = []
    else:
        keywords = (request.form.get("keywords") or "").strip()
        location = (
            request.form.get("location") or
            request.form.get("state") or
            request.form.get("country") or ""
        ).strip()
        platforms = request.form.getlist("platforms[]") or []

    # Validation
    if not keywords and not location:
        return jsonify({"error": "Either keywords or location is required."}), 400

    if not platforms:
        return jsonify({"error": "At least one platform must be selected"}), 400

    # Clean slate
    with DATA_LOCK:
        EXTRACTION_DATA.clear()

    EXTRACTION_STOP_EVENT.clear()
    EXTRACTING = True

    # Start thread
    EXTRACTION_THREAD = Thread(
        target=start_extraction_worker,
        args=(keywords, location, platforms),
        daemon=True
    )
    EXTRACTION_THREAD.start()

    app.logger.info(
        f"[EXTRACT] Started | keywords={keywords} | location={location} | platforms={platforms}"
    )

    return jsonify({"status": "Extraction started"})

@limiter.limit("10 per minute")
@app.route('/stop-extraction', methods=['POST'])
@user_login_required
def stop_extraction():
    """Stop ongoing extraction"""
    global EXTRACTING
    EXTRACTING = False
    EXTRACTION_STOP_EVENT.set()
    app.logger.info("Extraction stopped by user")
    return jsonify({"status": "Extraction stopped"})

@app.route('/view-extraction', methods=['GET'])
def view_extraction():
    """Get current extraction results"""
    if not session.get('user_logged_in'):
        return jsonify({"error": "Authentication required"}), 403
    
    try:
        with DATA_LOCK:
            total = len(EXTRACTION_DATA)
            numbers = EXTRACTION_DATA.copy()
        
        return jsonify({"total": total, "numbers": numbers})
        
    except Exception as e:
        app.logger.error(f"Error in view-extraction: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/export-data')
@user_login_required
def export_data():
    """Export data in various formats"""
    fmt = request.args.get('format', 'csv').lower()
    
    with DATA_LOCK:
        if fmt == 'csv':
            csv_data = "Number,Name,Address,Source\n"
            for entry in EXTRACTION_DATA:
                number = entry.get('number', '').replace(',', ' ')
                name = entry.get('name', '').replace(',', ' ')
                address = entry.get('address', '').replace(',', ' ')
                source = entry.get('source', '')
                csv_data += f"{number},{name},{address},{source}\n"
            
            response = Response(
                csv_data, 
                mimetype="text/csv",
                headers={"Content-disposition": "attachment; filename=extracted_data.csv"}
            )
            return response
        
        elif fmt == 'json':
            return jsonify(EXTRACTION_DATA)
        
        else:
            return jsonify({"error": "Unsupported format"}), 400

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login page"""
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        if username == ADMIN_USERNAME and verify_admin_password(password):
            session["is_admin"] = True
            session["admin_username"] = username
            session.permanent = True
            flash("Login successful!", "success")
            app.logger.info(f"Admin login successful for user: {username}")
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid credentials"
            app.logger.warning(f"Failed admin login attempt for user: {username}")
    
    return render_template("login.html", error=error)

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    extraction_active = EXTRACTING
    extracted_count = len(EXTRACTION_DATA)
    user_count = UserData.query.count()
    licenses = License.query.all()
    users = UserData.query.all()
    
    now_aware = datetime.now(timezone.utc)
    
    return render_template(
        "admin.html",
        extraction_active=extraction_active,
        extracted_count=extracted_count,
        user_count=user_count,
        licenses=licenses,
        users=users,
        timezone=timezone,
        now=now_aware,
        current_user=session.get("admin_username", "Admin")
    )

@app.route("/admin/logout")
def admin_logout():
    """Admin logout"""
    username = session.get("admin_username")
    session.clear()
    flash("You have been logged out.", "info")
    app.logger.info(f"Admin logout for user: {username}")
    return redirect(url_for("admin_login"))

@app.route("/admin/logs")
@admin_required
def admin_logs():
    """View application logs"""
    try:
        log_file = 'logs/app.log'
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = f.readlines()[-100:]
        else:
            logs = ["No log file available"]
    except Exception as e:
        logs = [f"Error reading logs: {str(e)}"]
        app.logger.error(f"Error reading log file: {str(e)}")
    
    return jsonify({"logs": logs})

@app.route("/generate-license", methods=["POST"])
@admin_required
def generate_license():
    """Generate new license key"""
    expiry_days = request.form.get("expiry_days", type=int, default=30)
    
    if expiry_days and expiry_days < 1:
        flash("Expiry days must be a positive number", "error")
        return redirect(url_for("admin_dashboard"))
    
    expiry = datetime.now(timezone.utc) + timedelta(days=expiry_days) if expiry_days else None
    
    new_license = License(
        key=secrets.token_hex(8).upper(),
        expiry=expiry
    )
    
    try:
        db.session.add(new_license)
        db.session.commit()
        flash(f"New license generated successfully: {new_license.key}", "success")
        app.logger.info(f"New license generated: {new_license.key}")
    except Exception as e:
        db.session.rollback()
        flash("Error generating license", "error")
        app.logger.error(f"Error generating license: {str(e)}")
    
    return redirect(url_for("admin_dashboard"))

@app.route("/revoke-license/<license_key>", methods=["POST"])
@admin_required
def revoke_license(license_key):
    """Revoke a license"""
    license_obj = License.query.filter_by(key=license_key).first()
    if license_obj:
        license_obj.revoked = True
        db.session.commit()
        flash("License revoked successfully!", "success")
        app.logger.info(f"License revoked: {license_key}")
    else:
        flash("License not found", "error")
    
    return redirect(url_for("admin_dashboard"))

@app.route("/stream-extraction")
@user_login_required
def stream_extraction():
    def event_stream():
        last_index = 0
        start_time = time.time()
        timeout = 300  # 5 minutes timeout

        while EXTRACTING and not EXTRACTION_STOP_EVENT.is_set():
            if time.time() - start_time > timeout:
                break
                
            time.sleep(1)
            
            with DATA_LOCK:
                current_count = len(EXTRACTION_DATA)
                new_items = EXTRACTION_DATA[last_index:]
                last_index = current_count

            for item in new_items:
                yield f"data: {json.dumps(item)}\n\n"

            # Send count update
            yield f"data: COUNT:{current_count}\n\n"

        # Extraction finished
        yield "data: END:stopped\n\n"

    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/user-login', methods=['POST'])
def user_login():
    """User login with license key"""
    try:
        license_key = request.form.get('license_key', '').strip().upper()
        
        if not license_key:
            return jsonify({"success": False, "error": "License key is required."})

        license_obj = License.query.filter_by(key=license_key).first()
        
        if not license_obj:
            return jsonify({"success": False, "error": "Invalid license key."})
        
        if license_obj.revoked:
            return jsonify({"success": False, "error": "License has been revoked."})

        # Check expiry
        if license_obj.expiry:
            expiry = license_obj.expiry
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)

            if expiry < datetime.now(timezone.utc):
                return jsonify({"success": False, "error": "License has expired."})

        # Update license usage
        license_obj.last_used = datetime.now(timezone.utc)
        license_obj.usage_count += 1
        
        db.session.commit()
        
        # Session setup
        session['user_logged_in'] = True
        session['license_key'] = license_key
        session.permanent = True
        
        app.logger.info(f"User successfully logged in with license: {license_key}")
        
        return jsonify({"success": True})
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error during user login: {str(e)}")
        return jsonify({"success": False, "error": "Server error occurred. Please try again."})

@app.route('/check-auth')
def check_auth():
    """Simple authentication check"""
    return jsonify({
        'authenticated': session.get('user_logged_in', False)
    })

@app.route('/user-logout', methods=['POST'])
def user_logout():
    """User logout"""
    license_key = session.get('license_key')
    session.pop('user_logged_in', None)
    session.pop('license_key', None)
    
    app.logger.info(f"User logged out with license: {license_key}")
    return jsonify({"success": True})

@app.route("/admin/edit-user/<username>", methods=["GET", "POST"])
@admin_required
def edit_user(username):
    """Edit user details"""
    user = UserData.query.filter_by(username=username).first_or_404()
    
    if request.method == "POST":
        flash(f"User {username} updated successfully", "success")
        return redirect(url_for("admin_dashboard"))
    
    return render_template("edit_user.html", user=user)

@app.route("/add-user", methods=["POST"])
@admin_required
def add_user():
    """Add new user"""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    email = request.form.get("email", "").strip()
    
    if not username or not password:
        flash("Username and password are required", "error")
        return redirect(url_for("admin_dashboard"))
    
    existing_user = UserData.query.filter_by(username=username).first()
    if existing_user:
        flash("Username already exists", "error")
        return redirect(url_for("admin_dashboard"))
    
    new_user = UserData(
        username=username,
        password_hash=generate_password_hash(password),
        email=email or None
    )
    
    try:
        db.session.add(new_user)
        db.session.commit()
        flash(f"User {username} created successfully", "success")
        app.logger.info(f"New user created: {username}")
    except Exception as e:
        db.session.rollback()
        flash("Error creating user", "error")
        app.logger.error(f"Error creating user: {str(e)}")
    
    return redirect(url_for("admin_dashboard"))

@app.route("/delete-user/<username>", methods=["POST"])
@admin_required
def delete_user(username):
    """Delete user"""
    user = UserData.query.filter_by(username=username).first()
    
    if user:
        try:
            db.session.delete(user)
            db.session.commit()
            flash(f"User {username} deleted successfully", "success")
            app.logger.info(f"User deleted: {username}")
        except Exception as e:
            db.session.rollback()
            flash("Error deleting user", "error")
            app.logger.error(f"Error deleting user: {str(e)}")
    else:
        flash("User not found", "error")
    
    return redirect(url_for("admin_dashboard"))

@app.route('/get-csrf')
def get_csrf():
    """Get CSRF token for AJAX requests"""
    return jsonify({'csrf_token': generate_csrf()})

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    app.logger.warning(f"404 Not Found: {request.url}")
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    app.logger.error(f"500 Internal Server Error: {str(error)}")
    db.session.rollback()
    return render_template('500.html'), 500

# -----------------------
# Enhanced Extraction Worker
# -----------------------
def start_extraction_worker(keywords, location, platforms):
    global EXTRACTING, EXTRACTION_DATA

    try:
        for platform in platforms:
            if not EXTRACTING or EXTRACTION_STOP_EVENT.is_set():
                break
                
            app.logger.info(f"Starting extraction from {platform}")
            
            # Run scraper for this platform
            results = run_scraper(platform, keywords, location)
            
            # Add results to global data
            with DATA_LOCK:
                EXTRACTION_DATA.extend(results)
            
            # Small delay between platforms
            time.sleep(2)
            
    except Exception as e:
        app.logger.error(f"Extraction worker error: {str(e)}")
        
    finally:
        EXTRACTING = False
        EXTRACTION_STOP_EVENT.clear()

# -----------------------
# Enhanced Health Check
# -----------------------
@app.route('/health')
def health_check():
    """Enhanced health check for production"""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'extraction_active': EXTRACTING,
        'data_count': len(EXTRACTION_DATA),
        'database_connected': True,
        'version': '1.0.0',
        'environment': os.environ.get('FLASK_ENV', 'development')
    }
    
    try:
        db.session.execute('SELECT 1')
    except Exception as e:
        health_status.update({
            'status': 'unhealthy',
            'database_connected': False,
            'error': str(e)
        })
        return jsonify(health_status), 500
    
    return jsonify(health_status)

# Add security headers
@app.after_request
def after_request(response):
    """Add security headers"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Server'] = 'DataExtractor'
    return response

@app.route('/favicon.ico')
def favicon():
    return '', 204

# -----------------------
# Run Application
# -----------------------
if __name__ == "__main__":
    print("[START] Starting Flask Application")
    print(f"[OK] CSRF protection: {'Enabled' if CSRF_AVAILABLE else 'Disabled'}")
    print("[OK] Database initialized")
    print("[OK] Logging configured")
    print("[OK] Admin panel available at /admin/login")
    print(f"[OK] Admin credentials - Username: {ADMIN_USERNAME}, Password: 112122")
    
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('PRODUCTION'):
        print("[PRODUCTION] Starting production server...")
        app.run(
            host='0.0.0.0',
            port=int(os.environ.get('PORT', 5000)),
            debug=False
        )
    else:
        print("[DEVELOPMENT] Starting development server...")
        app.run(
            debug=debug_mode,
            host=os.environ.get('FLASK_HOST', '0.0.0.0'),
            port=int(os.environ.get('FLASK_PORT', 5000))
        )