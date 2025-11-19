# werkzeug_patch.py - Temporary fix for Flask-WTF compatibility
import werkzeug.urls

# Add the missing url_encode function if it doesn't exist
if not hasattr(werkzeug.urls, 'url_encode'):
    werkzeug.urls.url_encode = werkzeug.urls.urlencode

# Apply the patch before importing Flask-WTF
import flask_wtf