# simple_scrapers.py - Lightweight scrapers for Render deployment
import requests
import re
import time
import random
from datetime import datetime, timezone
from urllib.parse import quote
from functools import wraps
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger("simple_scrapers")

# User agents for requests
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def retry(max_retries=2, delay_seconds=2):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*a, **kw)
                except Exception as e:
                    last_exc = e
                    logger.warning(f"[retry] {fn.__name__} failed attempt {attempt+1}/{max_retries+1}: {e}")
                    if attempt < max_retries:
                        time.sleep(delay_seconds * (attempt + 1))
            logger.error(f"[retry] {fn.__name__} exceeded retries: {last_exc}")
            return []
        return wrapper
    return deco

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    return session

PHONE_REGEX = re.compile(r'(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}(?: *x\d{1,5})?')

def format_phone(digits: str) -> str:
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return digits

def extract_phone_candidates(text: str) -> List[str]:
    candidates = PHONE_REGEX.findall(text or "")
    cleaned = []
    for c in candidates:
        digits = re.sub(r'\D', '', c)
        if len(digits) >= 10:
            if len(digits) > 11:
                digits = digits[-10:]
            cleaned.append(format_phone(digits))
    return list(dict.fromkeys(cleaned))

def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r'\s+', ' ', s).strip()

def _standard_result(number, name, address, source):
    return {
        "number": number or "N/A",
        "name": normalize_text(name) or "N/A",
        "address": normalize_text(address) or "N/A",
        "source": source,
        "timestamp": utc_now_iso()
    }

@retry(max_retries=2, delay_seconds=2)
def scrape_yellowpages(keywords, location):
    logger.info(f"🟡 Starting YellowPages scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.yellowpages.com/search?search_terms={q}&geo_location_terms={loc}"
    
    try:
        session = get_session()
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        results = []
        
        # Look for business cards
        cards = soup.find_all('div', class_=['result', 'search-result', 'business-result'])
        
        for card in cards[:15]:
            try:
                # Extract name
                name_elem = card.find('a', class_='business-name') or card.find('h2') or card.find('h3')
                name = name_elem.get_text().strip() if name_elem else ""
                
                # Extract address
                addr_elem = card.find(class_=['street-address', 'address', 'adr'])
                address = addr_elem.get_text().strip() if addr_elem else ""
                
                # Extract phone
                phone_elem = card.find(class_=['phones', 'phone'])
                phone = phone_elem.get_text().strip() if phone_elem else ""
                
                if not phone:
                    # Fallback: search for phone in the entire card
                    card_text = card.get_text()
                    phones = extract_phone_candidates(card_text)
                    phone = phones[0] if phones else ""
                
                if phone and name:
                    results.append(_standard_result(phone, name, address, "yellowpages"))
                    
            except Exception as e:
                continue
                
        logger.info(f"✅ YellowPages found {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"❌ YellowPages failed: {e}")
        return []

@retry(max_retries=2, delay_seconds=2)
def scrape_whitepages(keywords, location):
    logger.info(f"⚪ Starting WhitePages scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.whitepages.com/business/{q}/{loc}"
    
    try:
        session = get_session()
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        results = []
        
        # Look for business listings
        cards = soup.find_all('div', class_=['card', 'listing-card', 'result'])
        
        for card in cards[:15]:
            try:
                name_elem = card.find(class_=['name', 'business-name'])
                name = name_elem.get_text().strip() if name_elem else ""
                
                addr_elem = card.find(class_=['address', 'street-address'])
                address = addr_elem.get_text().strip() if addr_elem else ""
                
                phone_elem = card.find(href=re.compile(r'tel:')) or card.find(class_=['phone', 'phone-number'])
                phone = phone_elem.get_text().strip() if phone_elem else ""
                
                if not phone:
                    card_text = card.get_text()
                    phones = extract_phone_candidates(card_text)
                    phone = phones[0] if phones else ""
                
                if phone and name:
                    results.append(_standard_result(phone, name, address, "whitepages"))
                    
            except Exception:
                continue
                
        logger.info(f"✅ WhitePages found {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"❌ WhitePages failed: {e}")
        return []

@retry(max_retries=2, delay_seconds=2)
def scrape_manta(keywords, location):
    logger.info(f"🔵 Starting Manta scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.manta.com/search?search={q}&search_location={loc}"
    
    try:
        session = get_session()
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        results = []
        
        cards = soup.find_all('div', class_=['result', 'listing', 'business-card'])
        
        for card in cards[:15]:
            try:
                name_elem = card.find('h2') or card.find('h3') or card.find('a')
                name = name_elem.get_text().strip() if name_elem else ""
                
                addr_elem = card.find(class_=['address', 'location'])
                address = addr_elem.get_text().strip() if addr_elem else ""
                
                phone_elem = card.find(class_=['phone', 'telephone'])
                phone = phone_elem.get_text().strip() if phone_elem else ""
                
                if not phone:
                    card_text = card.get_text()
                    phones = extract_phone_candidates(card_text)
                    phone = phones[0] if phones else ""
                
                if phone and name:
                    results.append(_standard_result(phone, name, address, "manta"))
                    
            except Exception:
                continue
                
        logger.info(f"✅ Manta found {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"❌ Manta failed: {e}")
        return []

@retry(max_retries=2, delay_seconds=2)
def safe_scrape_yelp(keywords, location):
    logger.info(f"🔴 Starting Yelp scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    url = f"https://www.yelp.com/search?find_desc={q}&find_loc={loc}"
    
    try:
        session = get_session()
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        results = []
        
        cards = soup.find_all('article') or soup.find_all(class_=['business-listing', 'search-result'])
        
        for card in cards[:10]:
            try:
                name_elem = card.find('h3') or card.find('h4') or card.find('a')
                name = name_elem.get_text().strip() if name_elem else ""
                
                addr_elem = card.find('address') or card.find(class_=['address'])
                address = addr_elem.get_text().strip() if addr_elem else ""
                
                card_text = card.get_text()
                phones = extract_phone_candidates(card_text)
                phone = phones[0] if phones else ""
                
                if phone and name:
                    results.append(_standard_result(phone, name, address, "yelp"))
                    
            except Exception:
                continue
                
        logger.info(f"✅ Yelp found {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"❌ Yelp failed: {e}")
        return []

# Export the scrapers
__all__ = [
    'scrape_yellowpages',
    'scrape_whitepages', 
    'scrape_manta',
    'safe_scrape_yelp'
]