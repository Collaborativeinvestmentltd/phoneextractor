import requests
import re
import time
import random
from bs4 import BeautifulSoup
import logging
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import quote

# Set up logger
logger = logging.getLogger("scrapers")

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0"
]

def get_random_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

def scraper_error_handler(max_retries=2, delay=2):
    def decorator(scraper_func):
        @wraps(scraper_func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return scraper_func(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed for {scraper_func.__name__}: {e}")
                    if attempt < max_retries:
                        time.sleep(delay * (attempt + 1))
                        continue
                    logger.error(f"Max retries exceeded for {scraper_func.__name__}: {e}")
                    return []
            return []
        return wrapper
    return decorator

def validate_phone_number(phone_str):
    """Validate and clean phone numbers"""
    if not phone_str or phone_str == "N/A":
        return None
    
    # Remove common separators and spaces
    cleaned = re.sub(r'[\s\-\(\)\.\+]', '', str(phone_str))
    
    # US/Canada pattern: 10-11 digits, may start with 1
    if re.match(r'^1?\d{10}$', cleaned):
        # Format as (XXX) XXX-XXXX
        if len(cleaned) == 10:
            return f"({cleaned[:3]}) {cleaned[3:6]}-{cleaned[6:]}"
        elif len(cleaned) == 11 and cleaned.startswith('1'):
            return f"+1 ({cleaned[1:4]}) {cleaned[4:7]}-{cleaned[7:]}"
    
    return None

def safe_request(url, timeout=10):
    """Make safe HTTP request with error handling"""
    try:
        response = requests.get(url, headers=get_random_headers(), timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        logger.warning(f"Request failed for {url}: {e}")
        return None

def utc_now():
    return datetime.now(timezone.utc).isoformat()

# -----------------------
# REAL-TIME SCRAPERS
# -----------------------

@scraper_error_handler(max_retries=2)
def scrape_yellowpages(keywords, location):
    """Scrape YellowPages using requests"""
    results = []
    
    query = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    
    url = f"https://www.yellowpages.com/search?search_terms={query}&geo_location_terms={loc}"
    logger.info(f"Scraping YellowPages: {url}")
    
    response = safe_request(url, timeout=15)
    if not response:
        return results
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Find business cards
    cards = soup.find_all('div', class_=['result', 'search-result', 'sr-listing'])
    
    for card in cards[:20]:
        try:
            # Extract phone number
            phone_elem = card.find(['div', 'span'], class_=['phones', 'phone', 'phone-number'])
            phone_text = phone_elem.get_text(strip=True) if phone_elem else "N/A"
            
            validated_phone = validate_phone_number(phone_text)
            if not validated_phone:
                continue
            
            # Extract name
            name_elem = card.find(['a', 'h2'], class_=['business-name']) or card.find('h2')
            name_text = name_elem.get_text(strip=True) if name_elem else "N/A"
            
            # Extract address
            addr_elem = card.find(['div', 'span'], class_=['street-address', 'address', 'adr'])
            address_text = addr_elem.get_text(strip=True) if addr_elem else "N/A"
            
            result = {
                "number": validated_phone,
                "name": name_text,
                "address": address_text,
                "source": "yellowpages",
                "timestamp": utc_now()
            }
            results.append(result)
            logger.info(f"Found: {validated_phone} - {name_text}")
            
        except Exception as e:
            logger.warning(f"Error processing YellowPages card: {e}")
            continue
    
    return results

@scraper_error_handler(max_retries=2)
def scrape_whitepages(keywords, location):
    """Scrape WhitePages business directory"""
    results = []
    
    query = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    
    url = f"https://www.whitepages.com/business/{query}/{loc}"
    logger.info(f"Scraping WhitePages: {url}")
    
    response = safe_request(url, timeout=15)
    if not response:
        return results
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Look for business listings
    cards = soup.find_all('div', class_=['card', 'result', 'listing'])
    
    for card in cards[:15]:
        try:
            # Extract phone number
            phone_elem = card.find(['div', 'span'], class_=['phone', 'phone-number', 'tel'])
            phone_text = phone_elem.get_text(strip=True) if phone_elem else "N/A"
            
            validated_phone = validate_phone_number(phone_text)
            if not validated_phone:
                continue
            
            # Extract name
            name_elem = card.find(['h2', 'h3'], class_=['name', 'business-name']) or card.find('h2')
            name_text = name_elem.get_text(strip=True) if name_elem else "N/A"
            
            # Extract address
            addr_elem = card.find(['div', 'span'], class_=['address', 'location', 'street-address'])
            address_text = addr_elem.get_text(strip=True) if addr_elem else "N/A"
            
            result = {
                "number": validated_phone,
                "name": name_text,
                "address": address_text,
                "source": "whitepages",
                "timestamp": utc_now()
            }
            results.append(result)
            logger.info(f"Found: {validated_phone} - {name_text}")
            
        except Exception as e:
            logger.warning(f"Error processing WhitePages card: {e}")
            continue
    
    return results

@scraper_error_handler(max_retries=2)
def scrape_manta(keywords, location):
    """Scrape Manta business directory"""
    results = []
    
    query = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    
    url = f"https://www.manta.com/search?search={query}&search_location={loc}"
    logger.info(f"Scraping Manta: {url}")
    
    response = safe_request(url, timeout=15)
    if not response:
        return results
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Find business listings
    cards = soup.find_all('div', class_=['card', 'result'])
    
    for card in cards[:15]:
        try:
            # Extract phone number
            phone_elem = card.find('a', string=re.compile(r'\(\d{3}\)\s\d{3}-\d{4}'))
            if not phone_elem:
                phone_elem = card.find(['div', 'span'], class_=re.compile(r'phone'))
            phone_text = phone_elem.get_text(strip=True) if phone_elem else "N/A"
            
            validated_phone = validate_phone_number(phone_text)
            if not validated_phone:
                continue
            
            # Extract name
            name_elem = card.find(['h2', 'h3']) or card.find('a', class_=re.compile(r'name'))
            name_text = name_elem.get_text(strip=True) if name_elem else "N/A"
            
            # Extract address
            addr_elem = card.find(['div', 'span'], class_=re.compile(r'address'))
            address_text = addr_elem.get_text(strip=True) if addr_elem else "N/A"
            
            result = {
                "number": validated_phone,
                "name": name_text,
                "address": address_text,
                "source": "manta",
                "timestamp": utc_now()
            }
            results.append(result)
            logger.info(f"Found: {validated_phone} - {name_text}")
            
        except Exception as e:
            logger.warning(f"Error processing Manta card: {e}")
            continue
    
    return results

@scraper_error_handler(max_retries=2)
def safe_scrape_yelp(keywords, location):
    """Scrape Yelp business listings"""
    results = []
    
    query = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    
    url = f"https://www.yelp.com/search?find_desc={query}&find_loc={loc}"
    logger.info(f"Scraping Yelp: {url}")
    
    response = safe_request(url, timeout=15)
    if not response:
        return results
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Find business listings
    cards = soup.find_all('div', class_=re.compile(r'business'))
    
    for card in cards[:15]:
        try:
            # Yelp typically hides phone numbers, so we'll get business info
            name_elem = card.find(['h3', 'h4', 'a'], class_=re.compile(r'name|business'))
            name_text = name_elem.get_text(strip=True) if name_elem else "N/A"
            
            # Address
            addr_elem = card.find('address') or card.find('div', class_=re.compile(r'address'))
            address_text = addr_elem.get_text(strip=True) if addr_elem else "N/A"
            
            # Phone (often not available without interaction)
            phone_text = "N/A"
            
            result = {
                "number": phone_text,
                "name": name_text,
                "address": address_text,
                "source": "yelp",
                "timestamp": utc_now()
            }
            
            if name_text != "N/A":
                results.append(result)
                logger.info(f"Found Yelp: {name_text}")
            
        except Exception as e:
            logger.warning(f"Error processing Yelp card: {e}")
            continue
    
    return results

@scraper_error_handler(max_retries=2)
def scrape_411(keywords, location):
    """Scrape 411.com business directory"""
    results = []
    
    query = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    
    url = f"https://www.411.com/business/{query}/{loc}"
    logger.info(f"Scraping 411.com: {url}")
    
    response = safe_request(url, timeout=15)
    if not response:
        return results
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    cards = soup.find_all('div', class_=['result', 'card', 'listing'])
    
    for card in cards[:15]:
        try:
            # Phone number
            phone_elem = card.find(['div', 'span'], class_=['phone', 'phone-number', 'tel'])
            phone_text = phone_elem.get_text(strip=True) if phone_elem else "N/A"
            
            validated_phone = validate_phone_number(phone_text)
            if not validated_phone:
                continue
            
            # Name
            name_elem = card.find(['h2', 'h3']) or card.find('div', class_=re.compile(r'name'))
            name_text = name_elem.get_text(strip=True) if name_elem else "N/A"
            
            # Address
            addr_elem = card.find(['div', 'span'], class_=['address', 'location'])
            address_text = addr_elem.get_text(strip=True) if addr_elem else "N/A"
            
            result = {
                "number": validated_phone,
                "name": name_text,
                "address": address_text,
                "source": "411.com",
                "timestamp": utc_now()
            }
            results.append(result)
            logger.info(f"Found: {validated_phone} - {name_text}")
            
        except Exception as e:
            logger.warning(f"Error processing 411.com card: {e}")
            continue
    
    return results

@scraper_error_handler(max_retries=2)
def scrape_local_com(keywords, location):
    """Scrape Local.com business directory"""
    results = []
    
    query = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    
    url = f"https://www.local.com/business/results/?keyword={query}&location={loc}"
    logger.info(f"Scraping Local.com: {url}")
    
    response = safe_request(url, timeout=15)
    if not response:
        return results
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    cards = soup.find_all('div', class_=['listing', 'result', 'card'])
    
    for card in cards[:15]:
        try:
            # Phone number
            phone_elem = card.find(['div', 'span'], class_=['phone', 'phone-number', 'contact-phone'])
            phone_text = phone_elem.get_text(strip=True) if phone_elem else "N/A"
            
            validated_phone = validate_phone_number(phone_text)
            if not validated_phone:
                continue
            
            # Name
            name_elem = card.find(['h2', 'h3']) or card.find('div', class_=re.compile(r'title|name'))
            name_text = name_elem.get_text(strip=True) if name_elem else "N/A"
            
            # Address
            addr_elem = card.find(['div', 'span'], class_=['address', 'location'])
            address_text = addr_elem.get_text(strip=True) if addr_elem else "N/A"
            
            result = {
                "number": validated_phone,
                "name": name_text,
                "address": address_text,
                "source": "local.com",
                "timestamp": utc_now()
            }
            results.append(result)
            logger.info(f"Found: {validated_phone} - {name_text}")
            
        except Exception as e:
            logger.warning(f"Error processing Local.com card: {e}")
            continue
    
    return results

@scraper_error_handler(max_retries=2)
def safe_scrape_foursquare(keywords, location):
    """Scrape Foursquare venue listings"""
    results = []
    
    query = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    
    url = f"https://foursquare.com/explore?mode=url&near={loc}&q={query}"
    logger.info(f"Scraping Foursquare: {url}")
    
    response = safe_request(url, timeout=15)
    if not response:
        return results
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    cards = soup.find_all('div', class_=['venue', 'result', 'card'])
    
    for card in cards[:10]:
        try:
            # Name
            name_elem = card.find(['h2', 'h3']) or card.find('div', class_=re.compile(r'venueName|name'))
            name_text = name_elem.get_text(strip=True) if name_elem else "N/A"
            
            # Address
            addr_elem = card.find(['div', 'span'], class_=['venueAddress', 'address', 'location'])
            address_text = addr_elem.get_text(strip=True) if addr_elem else "N/A"
            
            # Phone (usually not available)
            phone_text = "N/A"
            
            result = {
                "number": phone_text,
                "name": name_text,
                "address": address_text,
                "source": "foursquare",
                "timestamp": utc_now()
            }
            
            if name_text != "N/A":
                results.append(result)
                logger.info(f"Found Foursquare: {name_text}")
            
        except Exception as e:
            logger.warning(f"Error processing Foursquare card: {e}")
            continue
    
    return results