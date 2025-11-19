# tasks.py
from celery import Celery
from flask import current_app
import os

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    
    celery.Task = ContextTask
    return celery

# Initialize Celery
celery = make_celery(app)

@celery.task(bind=True, max_retries=3)
def run_extraction_task(self, extraction_id, keywords, location, platforms):
    """Background task for running extraction"""
    from app import db, ExtractionLog
    from scrapers import run_scraper
    
    extraction_log = ExtractionLog.query.get(extraction_id)
    if not extraction_log:
        return {'status': 'ERROR', 'message': 'Extraction log not found'}
    
    try:
        total_records = 0
        for platform in platforms:
            if self.is_aborted():
                break
                
            # Update task state
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': platforms.index(platform) + 1,
                    'total': len(platforms),
                    'platform': platform,
                    'status': f'Scraping {platform}...'
                }
            )
            
            # Run scraper
            results = run_scraper(platform, keywords, location)
            total_records += len(results)
            
            # Store results (implement your storage logic)
            # ...
        
        # Update extraction log
        extraction_log.status = 'completed'
        extraction_log.records_extracted = total_records
        extraction_log.completed_at = datetime.utcnow()
        db.session.commit()
        
        return {'status': 'COMPLETED', 'records': total_records}
        
    except Exception as e:
        extraction_log.status = 'failed'
        extraction_log.error_message = str(e)
        db.session.commit()
        self.retry(countdown=60, exc=e)