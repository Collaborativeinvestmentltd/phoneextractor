import logging
from sqlalchemy.exc import SQLAlchemyError
import uuid
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
from flask_wtf import CSRFProtect
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from queue import Queue, Empty
# pandas and redis are optional at runtime in some environments — import safely
try:
    import pandas as pd
except Exception:
    pd = None
try:
    import redis
except Exception:
    redis = None
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import random
from io import BytesIO

# Instantiate commonly used Flask extensions at module level so models/extensions can reference them safely
db = SQLAlchemy()
migrate = None  # will be set to a Migrate() instance if available after CSRF block
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

# Import Migrate safely (may not be installed in minimal environments)
try:
    from flask_migrate import Migrate
    migrate = Migrate  # keep reference to class for later instantiation
except Exception:
    Migrate = None
    migrate = None

# Instantiate extension objects now that CSRF class is available
try:
    csrf = CSRFProtect()
except Exception:
    csrf = CSRFProtect()

# Instantiate limiter and db in a safe way — limiter needs get_remote_address from flask_limiter.util
try:
    limiter = Limiter(key_func=get_remote_address)
except Exception:
    # Fallback to a no-op limiter-like object with init_app method
    class _NoopLimiter:
        def init_app(self, app):
            pass
    limiter = _NoopLimiter()

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
# Import enhanced scrapers - REAL IMPLEMENTATIONS
# -----------------------
SCRAPERS_AVAILABLE = False
scraper_functions = {}

try:
    from enhanced_scrapers import (
        scrape_truepeoplesearch, scrape_spokeo, 
        scrape_fastpeoplesearch, scrape_zabasearch,
        scrape_yellowpages, scrape_whitepages, scrape_manta, safe_scrape_yelp
    )
    
    scraper_functions = {
        'truepeoplesearch': scrape_truepeoplesearch,
        'spokeo': scrape_spokeo,
        'fastpeoplesearch': scrape_fastpeoplesearch,
        'zabasearch': scrape_zabasearch,
        'yellowpages': scrape_yellowpages,  # Use the regular version
        'whitepages': scrape_whitepages,
        'manta': scrape_manta,
        'yelp': safe_scrape_yelp
    }
    SCRAPERS_AVAILABLE = True
    print("✅ ENHANCED REAL Scrapers integrated successfully")
    
except ImportError as e:
    print(f"❌ Enhanced scrapers import failed: {e}")
    SCRAPERS_AVAILABLE = False

# -----------------------
# Configuration
# -----------------------
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5

# -----------------------
# Enhanced Database Models
# -----------------------
class UserData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    
    licenses = db.relationship('License', backref='user', lazy=True, cascade='all, delete-orphan')
    extraction_sessions = db.relationship('ExtractionSession', backref='user', lazy=True)

class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expiry = db.Column(db.DateTime)
    max_usage = db.Column(db.Integer, default=1000)
    usage_count = db.Column(db.Integer, default=0)
    last_used = db.Column(db.DateTime)
    revoked = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user_data.id'))
    
    @property
    def is_expired(self):
        """Check if license is expired (timezone-safe)"""
        if not self.expiry:
            return False
        expiry_utc = self.expiry
        if expiry_utc.tzinfo is None:
            expiry_utc = expiry_utc.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        return expiry_utc < now_utc

class ExtractionSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user_data.id'), nullable=False)
    license_key = db.Column(db.String(64), nullable=False)
    keywords = db.Column(db.String(500))
    location = db.Column(db.String(200))
    platforms = db.Column(db.Text)  # JSON string of platforms
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='running')  # running, completed, failed, stopped
    total_results = db.Column(db.Integer, default=0)
    
    extracted_data = db.relationship('ExtractedData', backref='session', lazy=True, cascade='all, delete-orphan')

class ExtractedData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('extraction_session.id'), nullable=False)
    phone_number = db.Column(db.String(50), nullable=False)
    business_name = db.Column(db.String(500))
    address = db.Column(db.String(1000))
    source = db.Column(db.String(100), nullable=False)
    extracted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_valid = db.Column(db.Boolean, default=True)

# -----------------------
# App Factory
# -----------------------
def configure_logging(app):
    """Set up logging with rotation"""
    try:
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            print(f"✅ Created {log_dir}/ directory")

        # Simplified formatter without emoji replacement
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        )

        file_handler = RotatingFileHandler(
            os.path.join(log_dir, 'app.log'),
            maxBytes=app.config['LOG_MAX_BYTES'],
            backupCount=app.config['LOG_BACKUP_COUNT'],
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, app.config['LOG_LEVEL']))

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, app.config['LOG_LEVEL']))

        # Configure root logger
        logging.basicConfig(
            level=getattr(logging, app.config['LOG_LEVEL']),
            handlers=[file_handler, console_handler]
        )

        app.logger.addHandler(file_handler)
        app.logger.addHandler(console_handler)
        app.logger.setLevel(getattr(logging, app.config['LOG_LEVEL']))
        app.logger.info('Application startup')
        
    except Exception as e:
        print(f"⚠️ File logging failed: {e}, using console logging only")
        logging.basicConfig(
            level=getattr(logging, app.config['LOG_LEVEL']),
            format='%(asctime)s %(levelname)s: %(message)s'
        )

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Configure logging FIRST
    configure_logging(app)
    
    # Then initialize extensions
    db.init_app(app)
    if migrate and callable(migrate):
        # instantiate Migrate if available
        try:
            migrate_inst = migrate(app, db)
        except Exception:
            # fallback to using flask_migrate.Migrate().init_app if that pattern is needed
            try:
                migrate_inst = Migrate()
                migrate_inst.init_app(app, db)
            except Exception:
                pass
    try:
        csrf.init_app(app)
    except Exception:
        pass
    try:
        limiter.init_app(app)
    except Exception:
        # limiter may be a noop instance — ignore
        pass
    
    # Initialize Redis
    try:
        global redis_client
        if redis is not None:
            redis_client = redis.from_url(app.config['REDIS_URL'])
            redis_client.ping()
            app.logger.info("✅ Redis connected successfully")
        else:
            raise RuntimeError("redis library not available")
    except Exception as e:
        app.logger.warning(f"❌ Redis not available: {e}. Using in-memory cache.")
        redis_client = None
    
    # Configure logging
    configure_logging(app)
    
    # Add proxy fix for production
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # Session configuration
    @app.before_request
    def make_session_permanent():
        session.permanent = True
        app.permanent_session_lifetime = timedelta(hours=24)
    
    # Initialize database and run migrations if needed inside app context
    try:
        with app.app_context():
            init_database()
    except Exception as e:
        app.logger.error(f"Failed to initialize database at app startup: {e}")
    
    # MOVE THE reset-db ROUTE INSIDE THE APP FACTORY FUNCTION
    @app.route('/reset-db')
    def reset_db():
        """Temporary route to reset database - REMOVE AFTER USE"""
        try:
            # Drop all tables
            db.drop_all()
            
            # Create all tables with current schema
            db.create_all()
            
            # Create admin user
            admin_user = UserData(
                username="Admin",
                password_hash=generate_password_hash("112122"),
                email="admin@example.com",
                is_admin=True
            )
            db.session.add(admin_user)
            
            # Create sample licenses
            licenses = [
                License(key="80595DCBA3ED05E9", expiry=datetime.now(timezone.utc) + timedelta(days=365)),
                License(key="516C732CEB2F4F6D", expiry=datetime.now(timezone.utc) + timedelta(days=365)),
                License(key="TEST123456789ABC", expiry=datetime.now(timezone.utc) + timedelta(days=365))
            ]
            
            for license_obj in licenses:
                db.session.add(license_obj)
            
            db.session.commit()
            
            return """
            <h1>Database Reset Successfully!</h1>
            <p>Available License Keys:</p>
            <ul>
                <li>80595DCBA3ED05E9</li>
                <li>516C732CEB2F4F6D</li>
                <li>TEST123456789ABC</li>
            </ul>
            <p>Admin Login: Admin / 112122</p>
            <p><strong>REMEMBER TO REMOVE THIS ROUTE AFTER USE!</strong></p>
            """
            
        except Exception as e:
            return f"Error resetting database: {str(e)}"
    
    return app

# Initialize Database with Migration Support
# -----------------------
def init_database():
    """Initialize database - simplified for Render"""
    try:
        # First try to create all tables
        db.create_all()
        print("✅ Database tables created")
        
        # Check if admin user exists, if not create one
        admin_user = UserData.query.filter_by(username="Admin").first()
        if not admin_user:
            admin_user = UserData(
                username="Admin",
                password_hash=generate_password_hash("112122"),
                email="admin@example.com",
                is_admin=True
            )
            db.session.add(admin_user)
            print("✅ Admin user created")
        
        # Check if we have any licenses, if not create some
        if License.query.count() == 0:
            licenses = [
                License(key="80595DCBA3ED05E9", expiry=datetime.now(timezone.utc) + timedelta(days=365)),
                License(key="516C732CEB2F4F6D", expiry=datetime.now(timezone.utc) + timedelta(days=365)),
            ]
            for license_obj in licenses:
                db.session.add(license_obj)
            print("✅ Sample licenses created")
        
        db.session.commit()
        print("✅ Database initialized successfully")
        
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        # Try to recover by dropping and recreating
        try:
            db.session.rollback()
            db.drop_all()
            db.create_all()
            print("✅ Database recovered by recreating tables")
        except Exception as e2:
            print(f"❌ Database recovery failed: {e2}")

# Create app instance
app = create_app()

# -----------------------
# Global Variables
# -----------------------
EXTRACTION_DATA = []
DATA_LOCK = Lock()
EXTRACTION_THREAD = None
EXTRACTING = False
EXTRACTION_STOP_EVENT = Event()

# Thread pool for concurrent scraping
thread_pool = ThreadPoolExecutor(max_workers=5)

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
        if not session.get('user_logged_in') or not session.get('user_id'):
            app.logger.warning(f"Authentication failed: user_logged_in={session.get('user_logged_in')}, user_id={session.get('user_id')}")
            return jsonify({"error": "Authentication required"}), 403
        return f(*args, **kwargs)
    return decorated_function

# -----------------------
# Enhanced Helper Functions
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

def get_cache_key(platform, keywords, location):
    """Generate cache key for scraping results"""
    key_data = f"{platform}:{keywords}:{location}"
    return f"scrape_cache:{hash(key_data)}"

def cache_results(platform, keywords, location, results, ttl=3600):
    """Cache scraping results"""
    if not redis_client:
        return
    try:
        cache_key = get_cache_key(platform, keywords, location)
        redis_client.setex(cache_key, ttl, json.dumps(results))
    except Exception as e:
        app.logger.warning(f"Cache set failed: {e}")

def get_cached_results(platform, keywords, location):
    """Get cached scraping results"""
    if not redis_client:
        return None
    try:
        cache_key = get_cache_key(platform, keywords, location)
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        app.logger.warning(f"Cache get failed: {e}")
    return None

# -----------------------
# Enhanced Scraper Integration
# -----------------------
def run_scraper_with_retry(platform, keywords, location, max_retries=3):
    """Run scraper with exponential backoff retry mechanism"""
    for attempt in range(max_retries):
        try:
            # Check cache first
            cached_results = get_cached_results(platform, keywords, location)
            if cached_results:
                app.logger.info(f"✅ Using cached results for {platform}")
                return cached_results
            
            # Run the scraper
            scraper_func = scraper_functions[platform]
            app.logger.info(f"🚀 Running {platform} scraper (attempt {attempt + 1})")
            
            results = scraper_func(keywords, location)
            
            if not isinstance(results, list):
                app.logger.error(f"❌ Scraper {platform} returned non-list result: {type(results)}")
                continue
            
            # Cache successful results
            if results and len(results) > 0:
                cache_results(platform, keywords, location, results)
            
            app.logger.info(f"✅ {platform} scraper returned {len(results)} results")
            return results
            
        except Exception as e:
            app.logger.error(f"❌ {platform} scraper failed (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                app.logger.info(f"⏳ Retrying {platform} in {wait_time:.1f} seconds...")
                time.sleep(wait_time)
            else:
                app.logger.error(f"❌ {platform} scraper failed after {max_retries} attempts")
    
    return []

def run_scrapers_concurrently(platforms, keywords, location, session_id):
    """Run multiple scrapers concurrently and return results"""
    futures = {}
    all_results = []
    
    # Submit all scrapers to thread pool
    for platform in platforms:
        future = thread_pool.submit(run_scraper_with_retry, platform, keywords, location)
        futures[future] = platform
    
    # Collect results as they complete
    for future in as_completed(futures):
        platform = futures[future]
        try:
            platform_results = future.result()
            if platform_results:
                all_results.extend(platform_results)
                app.logger.info(f"✅ {platform} returned {len(platform_results)} results")
                
                # Update session progress in database
                try:
                    with app.app_context():
                        session = ExtractionSession.query.filter_by(session_id=session_id).first()
                        if session:
                            session.total_results = len(all_results)
                            db.session.commit()
                except Exception as e:
                    app.logger.error(f"Error updating session progress: {e}")
                    
        except Exception as e:
            app.logger.error(f"❌ {platform} scraper thread failed: {str(e)}")
    
    app.logger.info(f"🎯 TOTAL RESULTS: {len(all_results)} from {len(platforms)} platforms")
    return all_results

def update_extraction_session(session_id, results_count):
    """Update extraction session with progress - FIXED for background threads"""
    try:
        # Create application context for background thread
        with app.app_context():
            session = ExtractionSession.query.filter_by(session_id=session_id).first()
            if session:
                session.total_results += results_count
                db.session.commit()
    except Exception as e:
        app.logger.error(f"Error updating session: {e}")

# -----------------------
# Enhanced Routes
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
                           SCRAPERS_AVAILABLE=SCRAPERS_AVAILABLE)

# Helper to append results safely and persist to database
def append_result(item: dict, session_id=None):
    """Append result to global list and persist to database"""
    with DATA_LOCK:
        EXTRACTION_DATA.append(item)
    
    # Persist to database if session_id provided
    if session_id:
        try:
            with app.app_context():
                session_obj = ExtractionSession.query.filter_by(session_id=session_id).first()
                if session_obj:
                    extracted_data = ExtractedData(
                        session_id=session_obj.id,
                        phone_number=item.get('number', ''),
                        business_name=item.get('name', ''),
                        address=item.get('address', ''),
                        source=item.get('source', 'unknown')
                    )
                    db.session.add(extracted_data)
                    session_obj.total_results = len(EXTRACTION_DATA)
                    db.session.commit()
        except Exception as e:
            app.logger.error(f"Error saving to database: {e}")
            db.session.rollback()

# Helper to get snapshot safely
def get_snapshot():
    with DATA_LOCK:
        return EXTRACTION_DATA.copy()

# Enhanced request parsing with validation
def parse_extract_request(req):
    content_type = (req.content_type or "").lower()
    keywords = ""
    location = ""
    platforms = []

    if "application/json" in content_type:
        body = req.get_json(silent=True) or {}
        keywords = (body.get("keywords") or "").strip()
        location = (body.get("location") or "").strip()
        raw_platforms = body.get("platforms")
        if isinstance(raw_platforms, list):
            platforms = [p for p in raw_platforms if p and p in scraper_functions]
        elif isinstance(raw_platforms, str):
            platforms = [raw_platforms] if raw_platforms and raw_platforms in scraper_functions else []
    else:
        # Accept multipart/form-data or x-www-form-urlencoded or missing content-type
        keywords = (req.form.get("keywords") or "").strip()
        location = (
            req.form.get("location")
            or req.form.get("state")
            or req.form.get("country")
            or ""
        ).strip()
        platforms = [p for p in (req.form.getlist("platforms[]") or req.form.getlist("platforms")) 
                    if p and p in scraper_functions]

    # Validate and sanitize inputs
    if keywords and len(keywords) > 500:
        keywords = keywords[:500]
    if location and len(location) > 200:
        location = location[:200]

    return keywords, location, platforms

# Enhanced worker function with database persistence
def start_extraction_worker(keywords, location, platforms, session_id, license_key):
    """
    Enhanced worker with concurrent scraping and database persistence - FIXED
    """
    global EXTRACTING, EXTRACTION_DATA

    try:
        app.logger.info(f"🚀 ENHANCED WORKER STARTED - Session: {session_id}")
        app.logger.info(f"🔍 Keywords: '{keywords}', Location: '{location}', Platforms: {platforms}")

        # Clear previous results
        with DATA_LOCK:
            EXTRACTION_DATA.clear()

        # Run scrapers concurrently
        results = run_scrapers_concurrently(platforms, keywords, location, session_id)
        
        app.logger.info(f"✅ WORKER: Completed extraction with {len(results)} total results")

        # Store results in global variable and database
        if results:
            with DATA_LOCK:
                EXTRACTION_DATA.extend(results)
            
            # Persist results to database
            try:
                with app.app_context():
                    session_obj = ExtractionSession.query.filter_by(session_id=session_id).first()
                    if session_obj:
                        for result in results:
                            extracted_data = ExtractedData(
                                session_id=session_obj.id,
                                phone_number=result.get('number', ''),
                                business_name=result.get('name', ''),
                                address=result.get('address', ''),
                                source=result.get('source', 'unknown')
                            )
                            db.session.add(extracted_data)
                        session_obj.total_results = len(results)
                        session_obj.finished_at = datetime.now(timezone.utc)
                        session_obj.status = 'completed'
                        db.session.commit()
                        app.logger.info(f"✅ Saved {len(results)} results to database for session {session_id}")
            except Exception as e:
                app.logger.error(f"❌ Error saving results to database: {e}")
                db.session.rollback()

        # Mark session as completed
        try:
            with app.app_context():
                session_obj = ExtractionSession.query.filter_by(session_id=session_id).first()
                if session_obj:
                    if not session_obj.finished_at:
                        session_obj.finished_at = datetime.now(timezone.utc)
                    if session_obj.status == 'running':
                        session_obj.status = 'completed'
                    db.session.commit()
        except Exception as e:
            app.logger.error(f"Error updating session completion: {e}")

    except Exception as e:
        app.logger.exception(f"❌ WORKER: Unexpected error: {e}")
        # Mark session as failed
        try:
            with app.app_context():
                session_obj = ExtractionSession.query.filter_by(session_id=session_id).first()
                if session_obj:
                    session_obj.finished_at = datetime.now(timezone.utc)
                    session_obj.status = 'failed'
                    db.session.commit()
        except Exception as e:
            app.logger.error(f"Error updating session failure: {e}")

    finally:
        # Clear the stop event and mark extraction as finished
        EXTRACTION_STOP_EVENT.clear()
        EXTRACTING = False
        app.logger.info("🛑 WORKER: Worker exiting; EXTRACTING set to False")

# Enhanced extraction route with session management
@limiter.limit("10/minute")
@app.route("/extract", methods=["POST"])
@user_login_required
def start_extraction():
    global EXTRACTION_THREAD, EXTRACTING, EXTRACTION_DATA

    # Authentication check handled by decorator
    # Prevent double-start
    if EXTRACTING:
        return jsonify({"error": "Extraction already running"}), 400

    # Parse and validate input
    keywords, location, platforms = parse_extract_request(request)

    # Enhanced validation
    if (not keywords) and (not location):
        return jsonify({"error": "Either keywords or location is required."}), 400
    if not platforms:
        return jsonify({"error": "At least one platform must be selected"}), 400
    if len(platforms) > 10:
        return jsonify({"error": "Maximum 10 platforms allowed"}), 400

    # Get current user and license - FIXED
    license_key = session.get('license_key')
    user_id = session.get('user_id')  # <-- ADD THIS LINE

    if not session.get('user_logged_in') or not license_key or not user_id:
        return jsonify({"error": "User session invalid"}), 403

    # Create extraction session
    session_id = str(uuid.uuid4())
    extraction_session = ExtractionSession(
        session_id=session_id,
        user_id=user_id,  # <-- Now user_id is defined
        license_key=license_key,
        keywords=keywords,
        location=location,
        platforms=json.dumps(platforms)
    )
    
    try:
        db.session.add(extraction_session)
        db.session.commit()
    except Exception as e:
        app.logger.error(f"Error creating extraction session: {e}")
        return jsonify({"error": "Failed to start extraction session"}), 500

    # Clean slate: clear previous results under lock
    with DATA_LOCK:
        EXTRACTION_DATA.clear()

    # Clear stop event and set EXTRACTING before starting thread
    EXTRACTION_STOP_EVENT.clear()
    EXTRACTING = True

    # Start enhanced worker thread
    try:
        EXTRACTION_THREAD = Thread(
            target=start_extraction_worker,
            args=(keywords, location, platforms, session_id, license_key),
            daemon=True
        )
        EXTRACTION_THREAD.start()
    except Exception as e:
        EXTRACTING = False
        # Mark session as failed
        extraction_session.status = 'failed'
        extraction_session.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        
        app.logger.exception(f"[EXTRACT] Failed to start thread: {e}")
        return jsonify({"error": f"Failed to start extraction: {str(e)}"}), 500

    app.logger.info(f"[EXTRACT] Enhanced extraction started | session={session_id} | keywords={keywords} | platforms={platforms}")
    return jsonify({
        "status": "Extraction started",
        "session_id": session_id
    })

# Enhanced stop extraction
@limiter.limit("10/minute")
@app.route("/stop-extraction", methods=["POST"])
@csrf.exempt  # Add this line
@user_login_required
def stop_extraction():
    global EXTRACTING
    if not EXTRACTING:
        return jsonify({"status": "No extraction running"}), 200

    EXTRACTION_STOP_EVENT.set()
    EXTRACTING = False
    
    # Update any active sessions
    try:
        active_sessions = ExtractionSession.query.filter_by(status='running').all()
        for session in active_sessions:
            session.status = 'stopped'
            session.finished_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as e:
        app.logger.error(f"Error updating stopped sessions: {e}")
    
    app.logger.info("[EXTRACT] Stop requested by user")
    return jsonify({"status": "Extraction stop requested"})

# Enhanced view extraction with database support
@app.route("/view-extraction")
@user_login_required
def view_extraction():
    """Enhanced view extraction results with database support"""
    use_db = request.args.get('db', 'true').lower() == 'true'
    
    try:
        if use_db:
            # Get latest session for current user
            user_id = session.get('user_id')
            if user_id:
                latest_session = ExtractionSession.query.filter_by(user_id=user_id)\
                    .order_by(ExtractionSession.started_at.desc()).first()
                
                if latest_session:
                    extracted_data = ExtractedData.query.filter_by(session_id=latest_session.id)\
                        .order_by(ExtractedData.extracted_at.desc()).limit(1000).all()
                    
                    snapshot = [{
                        'number': item.phone_number,
                        'name': item.business_name,
                        'address': item.address,
                        'source': item.source
                    } for item in extracted_data]
                    
                    # Also update global variable for backward compatibility
                    with DATA_LOCK:
                        EXTRACTION_DATA.clear()
                        EXTRACTION_DATA.extend(snapshot)
                        
                    app.logger.info(f"📊 Database view: {len(snapshot)} results from session {latest_session.id}")
                else:
                    snapshot = get_snapshot()
            else:
                snapshot = get_snapshot()
        else:
            snapshot = get_snapshot()
        
        return jsonify({"total": len(snapshot), "numbers": snapshot})
        
    except Exception as e:
        app.logger.error(f"Error in view-extraction: {e}")
        # Fallback to global variable
        snapshot = get_snapshot()
        return jsonify({"total": len(snapshot), "numbers": snapshot})

# Enhanced export with multiple formats
@app.route('/export-data')
@user_login_required
def export_data():
    """Enhanced export data in various formats"""
    fmt = request.args.get('format', 'csv').lower()
    export_type = request.args.get('type', 'current')  # current, historical
    
    user_id = session.get('user_id')
    
    try:
        if export_type == 'historical' and user_id:
            # Export all user data
            extracted_data = ExtractedData.query\
                .join(ExtractionSession)\
                .filter(ExtractionSession.user_id == user_id)\
                .order_by(ExtractedData.extracted_at.desc()).all()
            data_list = [{
                'number': item.phone_number,
                'name': item.business_name,
                'address': item.address,
                'source': item.source,
                'extracted_at': item.extracted_at.isoformat()
            } for item in extracted_data]
        else:
            # Export current session data
            with DATA_LOCK:
                data_list = EXTRACTION_DATA.copy()
        
        if fmt == 'csv':
            csv_data = "Number,Name,Address,Source,Extracted_At\n"
            for entry in data_list:
                number = (entry.get('number', '') or '').replace(',', ' ').replace('"', '""')
                name = (entry.get('name', '') or '').replace(',', ' ').replace('"', '""')
                address = (entry.get('address', '') or '').replace(',', ' ').replace('"', '""')
                source = (entry.get('source', '') or '').replace(',', ' ').replace('"', '""')
                extracted_at = entry.get('extracted_at', '')
                
                csv_data += f'"{number}","{name}","{address}","{source}","{extracted_at}"\n'
            
            response = Response(
                csv_data, 
                mimetype="text/csv",
                headers={"Content-disposition": "attachment; filename=extracted_data.csv"}
            )
            return response
        
        elif fmt == 'excel':
            # Create Excel file using pandas if available
            if pd is None:
                return jsonify({"error": "Excel export requires pandas/openpyxl to be installed"}), 500
            df = pd.DataFrame(data_list)
            output = BytesIO()
            try:
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, sheet_name='Extracted Data', index=False)
            except Exception as e:
                app.logger.error(f"Excel export failed: {e}")
                return jsonify({"error": "Excel export failed"}), 500
            output.seek(0)
            
            response = Response(
                output.getvalue(),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-disposition": "attachment; filename=extracted_data.xlsx"}
            )
            return response
        
        elif fmt == 'json':
            return jsonify(data_list)
        
        else:
            return jsonify({"error": "Unsupported format"}), 400
            
    except Exception as e:
        app.logger.error(f"Export error: {e}")
        return jsonify({"error": "Export failed"}), 500

# Enhanced user registration
@app.route('/user-register', methods=['POST'])
def user_register():
    """User registration with license assignment"""
    try:
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip()
        license_key = request.form.get('license_key', '').strip().upper()
        
        # Validation
        if not username or not password or not license_key:
            return jsonify({"success": False, "error": "Username, password and license key are required."})
        
        if len(username) < 3:
            return jsonify({"success": False, "error": "Username must be at least 3 characters."})
        
        if len(password) < 6:
            return jsonify({"success": False, "error": "Password must be at least 6 characters."})
        
        # Check if username exists
        existing_user = UserData.query.filter_by(username=username).first()
        if existing_user:
            return jsonify({"success": False, "error": "Username already exists."})
        
        # Validate license
        license_obj = License.query.filter_by(key=license_key).first()
        if not license_obj:
            return jsonify({"success": False, "error": "Invalid license key."})
        
        if license_obj.revoked:
            return jsonify({"success": False, "error": "License has been revoked."})
        
        if license_obj.user_id:
            return jsonify({"success": False, "error": "License is already assigned to another user."})
        
        # Check expiry
        if license_obj.expiry:
            expiry = license_obj.expiry
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry < datetime.now(timezone.utc):
                return jsonify({"success": False, "error": "License has expired."})
        
        # Create user
        new_user = UserData(
            username=username,
            password_hash=generate_password_hash(password),
            email=email or None
        )
        
        db.session.add(new_user)
        db.session.flush()  # Get the user ID
        
        # Assign license to user
        license_obj.user_id = new_user.id
        
        db.session.commit()
        
        # Auto-login
        session['user_logged_in'] = True
        session['user_id'] = new_user.id
        session['username'] = username
        session['license_key'] = license_key
        session.permanent = True
        
        app.logger.info(f"New user registered: {username} with license: {license_key}")
        
        return jsonify({"success": True, "message": "Registration successful!"})
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error during user registration: {str(e)}")
        return jsonify({"success": False, "error": "Server error occurred. Please try again."})

# Enhanced user login
@app.route('/user-login', methods=['POST'])
def user_login():
    """Enhanced user login with better error handling"""
    try:
        license_key = request.form.get('license_key', '').strip().upper()
        
        if not license_key:
            return jsonify({"success": False, "error": "License key is required."})

        # Try to find the license
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
        
        # Get or create user
        user = UserData.query.get(license_obj.user_id) if license_obj.user_id else None
        
        if not user:
            # Create a temporary user for this license
            temp_username = f"user_{license_key[:8]}"
            user = UserData.query.filter_by(username=temp_username).first()
            if not user:
                user = UserData(
                    username=temp_username,
                    password_hash=generate_password_hash(secrets.token_hex(16)),
                    is_active=True
                )
                db.session.add(user)
                db.session.flush()
            
            # Assign license to user
            license_obj.user_id = user.id
        
        # Set session variables
        session['user_logged_in'] = True
        session['license_key'] = license_key
        session['user_id'] = user.id
        session['username'] = user.username
        session.permanent = True
        
        # Update user last login
        user.last_login = datetime.now(timezone.utc)
        
        db.session.commit()
        
        print(f"✅ User login successful: {user.username} with license {license_key}")
        return jsonify({"success": True, "username": user.username})
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Login error: {str(e)}")
        return jsonify({"success": False, "error": "Database error. Please try again."})

# Admin login route
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login page"""
    # If already logged in as admin, redirect to dashboard
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        if username == ADMIN_USERNAME and verify_admin_password(password):
            session["is_admin"] = True
            session["admin_username"] = username
            flash("Admin login successful", "success")
            app.logger.info(f"Admin user logged in: {username}")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid admin credentials", "error")
            app.logger.warning(f"Failed admin login attempt for username: {username}")
    
    return render_template("admin_login.html")

# Enhanced admin routes - SIMPLER FIX
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Enhanced admin dashboard"""
    extraction_active = EXTRACTING
    extracted_count = len(EXTRACTION_DATA)
    user_count = UserData.query.count()
    licenses = License.query.all()
    users = UserData.query.all()
    
    # Enhanced stats
    total_extractions = ExtractionSession.query.count()
    active_sessions = ExtractionSession.query.filter_by(status='running').count()
    total_extracted_data = ExtractedData.query.count()
    
    # Use naive datetime to avoid timezone issues
    now_naive = datetime.now()
    
    return render_template(
        "admin.html",
        extraction_active=extraction_active,
        extracted_count=extracted_count,
        user_count=user_count,
        licenses=licenses,
        users=users,
        total_extractions=total_extractions,
        active_sessions=active_sessions,
        total_extracted_data=total_extracted_data,
        now=now_naive,
        current_user=session.get("admin_username", "Admin")
    )

# Admin logout route - CORRECTED
@app.route("/admin/logout")
def admin_logout():
    """Admin logout"""
    session.pop("is_admin", None)
    session.pop("admin_username", None)
    flash("Admin logged out successfully", "success")
    return redirect(url_for("admin_login"))

# License generation route - CORRECTED
@app.route("/generate-license", methods=["POST"])
@admin_required
def generate_license():
    """Generate new license key with enhanced options"""
    expiry_days = request.form.get("expiry_days", type=int, default=30)
    max_usage = request.form.get("max_usage", type=int, default=1000)
    user_id = request.form.get("user_id", type=int)
    
    if expiry_days and expiry_days < 1:
        flash("Expiry days must be a positive number", "error")
        return redirect(url_for("admin_dashboard"))
    
    if max_usage and max_usage < 1:
        flash("Max usage must be a positive number", "error")
        return redirect(url_for("admin_dashboard"))
    
    expiry = datetime.now(timezone.utc) + timedelta(days=expiry_days) if expiry_days else None
    
    new_license = License(
        key=secrets.token_hex(8).upper(),
        expiry=expiry,
        max_usage=max_usage,
        user_id=user_id
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

@app.route("/admin/license/<license_key>/revoke", methods=["POST"])
@admin_required
def admin_revoke_license(license_key):
    try:
        lic = License.query.filter_by(key=license_key).first()
        if not lic:
            return jsonify({"success": False, "error": "License not found"}), 404
        lic.revoked = True
        db.session.commit()
        app.logger.info(f"Admin revoked license {license_key}")
        return jsonify({"success": True, "message": "License revoked"})
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception(f"Error revoking license {license_key}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

@app.route("/admin/license/<license_key>/extend", methods=["POST"])
@admin_required
def admin_extend_license(license_key):
    try:
        days = int(request.form.get("days", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid days value"}), 400

    if days <= 0:
        return jsonify({"success": False, "error": "Days must be positive"}), 400

    lic = License.query.filter_by(key=license_key).first()
    if not lic:
        return jsonify({"success": False, "error": "License not found"}), 404

    try:
        now = datetime.now(timezone.utc)
        if lic.expiry is None:
            new_expiry = now + timedelta(days=days)
        else:
            expiry = lic.expiry
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            new_expiry = expiry + timedelta(days=days)
        lic.expiry = new_expiry
        db.session.commit()
        app.logger.info(f"Admin extended license {license_key} by {days} days to {new_expiry.isoformat()}")
        return jsonify({"success": True, "new_expiry": lic.expiry.isoformat()})
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception(f"Error extending license {license_key}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

@app.route("/admin/license/<license_key>/reduce", methods=["POST"])
@admin_required
def admin_reduce_license(license_key):
    try:
        days = int(request.form.get("days", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid days value"}), 400

    if days <= 0:
        return jsonify({"success": False, "error": "Days must be positive"}), 400

    lic = License.query.filter_by(key=license_key).first()
    if not lic:
        return jsonify({"success": False, "error": "License not found"}), 404

    if not lic.expiry:
        return jsonify({"success": False, "error": "Cannot reduce an open-ended license"}), 400

    try:
        expiry = lic.expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        new_expiry = expiry - timedelta(days=days)
        # Prevent making expiry earlier than now (optional policy)
        now = datetime.now(timezone.utc)
        if new_expiry < now:
            lic.expiry = now
        else:
            lic.expiry = new_expiry
        db.session.commit()
        app.logger.info(f"Admin reduced license {license_key} by {days} days to {lic.expiry.isoformat()}")
        return jsonify({"success": True, "new_expiry": lic.expiry.isoformat()})
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception(f"Error reducing license {license_key}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

@app.route("/admin/license/<license_key>/reset-usage", methods=["POST"])
@admin_required
def admin_reset_license_usage(license_key):
    lic = License.query.filter_by(key=license_key).first()
    if not lic:
        return jsonify({"success": False, "error": "License not found"}), 404
    try:
        lic.usage_count = 0
        lic.last_used = None
        db.session.commit()
        app.logger.info(f"Admin reset usage for license {license_key}")
        return jsonify({"success": True, "message": "Usage reset"})
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception(f"Error resetting usage for license {license_key}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

@app.route("/admin/license/<license_key>/assign", methods=["POST"])
@admin_required
def admin_assign_license(license_key):
    # assign to username in form, or empty to unassign
    username = (request.form.get("username") or "").strip()
    lic = License.query.filter_by(key=license_key).first()
    if not lic:
        return jsonify({"success": False, "error": "License not found"}), 404

    try:
        if username == "":
            lic.user_id = None
            db.session.commit()
            app.logger.info(f"Admin unassigned license {license_key}")
            return jsonify({"success": True, "message": "Unassigned"})
        user = UserData.query.filter_by(username=username).first()
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404
        lic.user_id = user.id
        db.session.commit()
        app.logger.info(f"Admin assigned license {license_key} to user {username}")
        return jsonify({"success": True, "message": f"Assigned to {username}"})
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception(f"Error assigning license {license_key}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

# Add enhanced user management
@app.route("/admin/edit-user/<int:user_id>", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    """Enhanced user editing"""
    user = UserData.query.get_or_404(user_id)
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        is_active = request.form.get("is_active") == "on"
        is_admin = request.form.get("is_admin") == "on"
        
        if not username:
            flash("Username is required", "error")
            return render_template("edit_user.html", user=user)
        
        # Check if username is taken by another user
        existing_user = UserData.query.filter(UserData.username == username, UserData.id != user_id).first()
        if existing_user:
            flash("Username already taken", "error")
            return render_template("edit_user.html", user=user)
        
        user.username = username
        user.email = email
        user.is_active = is_active
        user.is_admin = is_admin
        
        # Update password if provided
        new_password = request.form.get("new_password")
        if new_password:
            if len(new_password) < 6:
                flash("Password must be at least 6 characters", "error")
                return render_template("edit_user.html", user=user)
            user.password_hash = generate_password_hash(new_password)
        
        try:
            db.session.commit()
            flash(f"User {username} updated successfully", "success")
            return redirect(url_for("admin_dashboard"))
        except Exception as e:
            db.session.rollback()
            flash("Error updating user", "error")
            app.logger.error(f"Error updating user: {str(e)}")
    
    return render_template("edit_user.html", user=user)

# Add user sessions view
@app.route("/admin/user-sessions/<int:user_id>")
@admin_required
def user_sessions(user_id):
    """View user extraction sessions"""
    user = UserData.query.get_or_404(user_id)
    sessions = ExtractionSession.query.filter_by(user_id=user_id)\
        .order_by(ExtractionSession.started_at.desc()).all()
    
    return render_template("user_sessions.html", user=user, sessions=sessions)

# Enhanced health check
@app.route('/health')
def health_check():
    """Enhanced health check for production"""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'extraction_active': EXTRACTING,
        'data_count': len(EXTRACTION_DATA),
        'database_connected': True,
        'redis_connected': redis_client is not None,
        'thread_pool_active': thread_pool._threads is not None,
        'version': '2.0.0',
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
    
    try:
        if redis_client:
            redis_client.ping()
    except Exception as e:
        health_status.update({
            'redis_connected': False,
            'warning': f'Redis: {str(e)}'
        })
    
    return jsonify(health_status)

# -----------------------
# Run Application
# -----------------------
if __name__ == "__main__":
    print("[START] Starting Enhanced Flask Application")
    print(f"[OK] CSRF protection: {'Enabled' if CSRF_AVAILABLE else 'Disabled'}")
    print("[OK] Database initialized with enhanced models")
    print("[OK] Redis caching: Enabled" if redis_client else "[WARN] Redis caching: Disabled")
    print("[OK] Concurrent scraping enabled")
    print("[OK] Enhanced admin panel available")
    print(f"[OK] Admin credentials - Username: {ADMIN_USERNAME}, Password: 112122")
    
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