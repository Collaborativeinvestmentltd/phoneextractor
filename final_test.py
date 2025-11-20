# final_test.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Test direct scraper call
from scrapers import scrape_yellowpages
print("🚀 Direct scraper test:")
results = scrape_yellowpages("pizza", "New York")
print(f"📊 Direct call got {len(results)} results")
for i, r in enumerate(results[:3]):
    print(f"  {i+1}. {r['name']} - {r['number']} - {r['source']}")

print("\n" + "="*50)

# Test through app's run_scraper function
from app import run_scraper
print("🚀 App run_scraper test:")
app_results = run_scraper('yellowpages', 'pizza', 'New York')
print(f"📊 App call got {len(app_results)} results")
for i, r in enumerate(app_results[:3]):
    print(f"  {i+1}. {r['name']} - {r['number']} - {r['source']}")