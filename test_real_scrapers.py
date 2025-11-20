# test_real_scrapers.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scrapers import scrape_yellowpages

print("🚀 Testing REAL YellowPages scraper...")
results = scrape_yellowpages("pizza", "New York")
print(f"📊 Got {len(results)} results:")
for i, result in enumerate(results):
    print(f"  {i+1}. {result['name']} - {result['number']} - {result['source']}")