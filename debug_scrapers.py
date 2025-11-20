# debug_scrapers.py
import os
import sys
import logging

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up logging
logging.basicConfig(level=logging.DEBUG)

def test_scraper_import():
    print("🔍 Testing scraper imports...")
    try:
        from scrapers import (
            scrape_yellowpages, scrape_whitepages, scrape_manta,
            scrape_411, scrape_local_com, safe_scrape_yelp, safe_scrape_foursquare
        )
        print("✅ All scrapers imported successfully!")
        
        # Test if they're real functions or mocks
        scrapers = {
            'yellowpages': scrape_yellowpages,
            'whitepages': scrape_whitepages,
            'manta': scrape_manta,
            '411': scrape_411,
            'local_com': scrape_local_com,
            'yelp': safe_scrape_yelp,
            'foursquare': safe_scrape_foursquare
        }
        
        for name, func in scrapers.items():
            if "mock" in func.__code__.co_filename:
                print(f"❌ {name}: Using MOCK scraper")
            else:
                print(f"✅ {name}: Using REAL scraper")
                
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_playwright():
    print("\n🔍 Testing Playwright...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto('https://httpbin.org/html')
            title = page.title()
            browser.close()
            print(f"✅ Playwright working! Test page title: {title}")
            return True
    except Exception as e:
        print(f"❌ Playwright failed: {e}")
        return False

def test_single_scraper():
    print("\n🔍 Testing a single scraper...")
    try:
        from scrapers import scrape_yellowpages
        print("Testing YellowPages scraper with 'restaurants' in 'New York'...")
        results = scrape_yellowpages("restaurants", "New York")
        print(f"Results: {len(results)} items")
        for i, result in enumerate(results[:3]):
            print(f"  {i+1}. {result}")
        return True
    except Exception as e:
        print(f"❌ Scraper test failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting scraper diagnostics...")
    test_scraper_import()
    test_playwright()
    test_single_scraper()