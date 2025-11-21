# enhanced_scrapers.py - REAL SCRAPER IMPLEMENTATIONS
import os
import re
import time
import random
import logging
from datetime import datetime, timezone
from urllib.parse import quote
from functools import wraps
from typing import List, Dict, Optional

# Configure logging
logger = logging.getLogger("enhanced_scrapers")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Import Playwright
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
    PLAYWRIGHT_AVAILABLE = True
    logger.info("✅ Playwright successfully imported")
except ImportError as e:
    logger.error(f"❌ Playwright import failed: {e}")
    PLAYWRIGHT_AVAILABLE = False

# Configuration
PROXY_POOL = [p.strip() for p in os.environ.get("PROXY_POOL", "").split(",") if p.strip()]
PLAYWRIGHT_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() not in ("0", "false", "no")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Utility functions
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

def choose_proxy() -> Optional[Dict]:
    if not PROXY_POOL:
        return None
    raw = random.choice(PROXY_POOL)
    m = re.match(r'(?P<scheme>https?|socks5(?:h)?):\/\/(?:(?P<user>[^:@]+)(?::(?P<pw>[^@]+))?@)?(?P<host>[^:\/]+):(?P<port>\d+)', raw)
    if not m:
        return {"server": raw}
    gd = m.groupdict()
    server = f"{gd['scheme']}://{gd['host']}:{gd['port']}"
    out = {"server": server}
    if gd.get('user'):
        out['username'] = gd['user']
    if gd.get('pw'):
        out['password'] = gd['pw']
    return out

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.navigator.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
"""

def human_wait(min_s=0.2, max_s=1.0):
    time.sleep(random.uniform(min_s, max_s))

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
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

def _launch_browser_and_run(func, proxy=None, headless=PLAYWRIGHT_HEADLESS, timeout_ms=30000):
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available - using mock")
        return [{
            'number': f"555-{int(time.time()) % 10000:04d}",
            'name': f'Sample Business {int(time.time()) % 1000}',
            'address': f'123 Main St, Sample City',
            'source': 'mock-fallback'
        }]
    
    try:
        logger.info("Launching real browser with Playwright...")
        with sync_playwright() as p:
            launch_args = {
                "headless": headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-infobars",
                ]
            }
            if proxy:
                launch_args["proxy"] = proxy
                logger.info(f"Using proxy: {proxy.get('server', 'unknown')}")

            browser = p.chromium.launch(**launch_args)
            ua = random.choice(USER_AGENTS)
            context_args = {
                "user_agent": ua,
                "viewport": {"width": 1280, "height": 720},
                "locale": "en-US",
            }
            context = browser.new_context(**context_args)
            page = context.new_page()
            
            try:
                page.add_init_script(STEALTH_SCRIPT)
            except Exception:
                pass

            result = func(page, context, browser)
            
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
                
            logger.info(f"Browser execution completed, returned {len(result) if isinstance(result, list) else 'non-list'} results")
            return result
            
    except PlaywrightError as e:
        logger.error(f"Playwright error: {e}")
        return []
    except Exception as e:
        logger.error(f"Browser launch/run error: {e}")
        return []

def safe_visit_and_get_html(page, url, wait_selector=None, timeout=15000):
    try:
        logger.info(f"Visiting: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        logger.info(f"Successfully loaded: {url}")
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout while loading: {url}")
    except Exception as e:
        logger.warning(f"Error visiting {url}: {e}")

    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, timeout=5000)
        except Exception:
            pass

    human_wait(0.1, 0.45)
    
    try:
        return page.content()
    except Exception:
        return page.inner_text("body") or ""

def extract_phone_from_page(page) -> List[str]:
    candidates = []

    # Extract from tel: links
    try:
        tel_elements = page.query_selector_all("a[href^='tel:'], a[href*='phone'], [data-phone], [itemprop*='telephone']")
        for el in tel_elements:
            try:
                href = el.get_attribute("href") or ""
                text = el.inner_text() or ""
                if href and 'tel:' in href:
                    phone = re.sub(r'^\s*tel:\+?', '', href, flags=re.I)
                    phone = re.sub(r'\D', '', phone)
                    if len(phone) >= 10:
                        candidates.append(format_phone(phone[-10:] if len(phone) >= 10 else phone))
                found = extract_phone_candidates(text)
                candidates.extend(found)
            except Exception:
                continue
    except Exception:
        pass

    # Extract from phone elements
    query_selectors = [
        "span.phone", ".phone", ".phones", ".contact-phone", ".contact .phone",
        "[class*='phone']", "[id*='phone']", "[role='phone']"
    ]
    for sel in query_selectors:
        try:
            els = page.query_selector_all(sel)
            for el in els:
                try:
                    text = el.inner_text() or ""
                    found = extract_phone_candidates(text)
                    candidates.extend(found)
                except Exception:
                    continue
        except Exception:
            continue

    # Extract from full page text
    try:
        body_text = page.inner_text("body") or ""
        candidates.extend(extract_phone_candidates(body_text[:200000]))
    except Exception:
        pass

    seen = []
    for c in candidates:
        if c not in seen and c:
            seen.append(c)
    return seen

def _run_playwright_scrape(target_url, extractor_func, proxy=None, headless=PLAYWRIGHT_HEADLESS):
    def run(page, context, browser):
        logger.info(f"[playwright] Visiting {target_url}")
        html = safe_visit_and_get_html(page, target_url, wait_selector=None, timeout=25000)
        
        try:
            res = extractor_func(page, html)
            if res:
                logger.info(f"Extractor found {len(res)} results")
                return res
        except Exception as e:
            logger.warning(f"Extractor func error: {e}")

        try:
            human_wait(0.5, 1.2)
            res = extractor_func(page, page.content())
            if res:
                return res
        except Exception:
            pass

        try:
            phones = extract_phone_from_page(page)
            results = []
            for p in phones[:25]:
                results.append(_standard_result(p, page.title() or "N/A", "", "fallback"))
            logger.info(f"Fallback extraction found {len(results)} phone numbers")
            return results
        except Exception as e:
            logger.error(f"Fallback extraction failed: {e}")
            return []

    return _launch_browser_and_run(run, proxy=proxy, headless=headless)

# REAL SCRAPER IMPLEMENTATIONS

@retry(max_retries=2, delay_seconds=2)
def scrape_truepeoplesearch(keywords, location):
    """Scrape TruePeopleSearch for people/business information"""
    logger.info(f"🔍 Starting TruePeopleSearch scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else ""
    loc = quote(location) if location else ""
    
    if q and loc:
        url = f"https://www.truepeoplesearch.com/results?name={q}&citystatezip={loc}"
    elif q:
        url = f"https://www.truepeoplesearch.com/results?name={q}"
    elif loc:
        url = f"https://www.truepeoplesearch.com/results?citystatezip={loc}"
    else:
        return []

    def extractor(page, html):
        results = []
        try:
            # TruePeopleSearch specific selectors
            cards = page.query_selector_all(".card, .result-card, .person-card, .search-result")
            logger.info(f"Found {len(cards)} cards on TruePeopleSearch")
            
            for card in cards:  # Process ALL cards
                try:
                    # Name extraction
                    name_el = card.query_selector("h2, h3, .person-name, .name, [class*='name']")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    # Address extraction
                    addr_el = card.query_selector(".address, .location, [class*='address']")
                    addr_text = addr_el.inner_text().strip() if addr_el else ""
                    
                    # Phone extraction
                    phone_el = card.query_selector(".phone, .phonenumber, [class*='phone']")
                    phone_text = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone_text:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone_text = pcs[0] if pcs else ""
                    
                    if phone_text and name_text:
                        results.append(_standard_result(phone_text, name_text, addr_text, "truepeoplesearch"))
                        logger.info(f"✅ Found: {name_text} - {phone_text}")
                        
                except Exception as e:
                    continue
                    
        except Exception as e:
            logger.error(f"TruePeopleSearch extraction error: {e}")
            
        if not results:
            phones = extract_phone_from_page(page)
            for p in phones[:10]:
                results.append(_standard_result(p, page.title() or "N/A", "", "truepeoplesearch-fallback"))
                
        logger.info(f"TruePeopleSearch returning {len(results)} results")
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_spokeo(keywords, location):
    """Scrape Spokeo for people/business information"""
    logger.info(f"🔍 Starting Spokeo scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else ""
    loc = quote(location) if location else ""
    
    if q and loc:
        url = f"https://www.spokeo.com/{q}?location={loc}"
    elif q:
        url = f"https://www.spokeo.com/{q}"
    elif loc:
        url = f"https://www.spokeo.com/location/{loc}"
    else:
        return []

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".card, .person-card, .search-result, [data-testid*='result']")
            logger.info(f"Found {len(cards)} cards on Spokeo")
            
            for card in cards:  # Process ALL cards
                try:
                    name_el = card.query_selector("h2, h3, .person-name, .name")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".address, .location, [class*='address']")
                    addr_text = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector(".phone, [class*='phone']")
                    phone_text = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone_text:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone_text = pcs[0] if pcs else ""
                    
                    if phone_text and name_text:
                        results.append(_standard_result(phone_text, name_text, addr_text, "spokeo"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"Spokeo extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_fastpeoplesearch(keywords, location):
    """Scrape FastPeopleSearch for information"""
    logger.info(f"🔍 Starting FastPeopleSearch scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else ""
    loc = quote(location) if location else ""
    
    url = f"https://www.fastpeoplesearch.com/"
    if q or loc:
        url += "?"
        if q:
            url += f"name={q}"
        if loc:
            url += f"&location={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".card, .person-info, .search-result, [class*='result']")
            logger.info(f"Found {len(cards)} cards on FastPeopleSearch")
            
            for card in cards:  # Process ALL cards
                try:
                    name_el = card.query_selector("h2, h3, .person-name, .name")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".address, .location")
                    addr_text = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector(".phone, [class*='phone']")
                    phone_text = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone_text:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone_text = pcs[0] if pcs else ""
                    
                    if phone_text and name_text:
                        results.append(_standard_result(phone_text, name_text, addr_text, "fastpeoplesearch"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"FastPeopleSearch extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_zabasearch(keywords, location):
    """Scrape ZabaSearch for information"""
    logger.info(f"🔍 Starting ZabaSearch scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else ""
    loc = quote(location) if location else ""
    
    url = "https://www.zabasearch.com/"
    if q or loc:
        url += "?"
        if q:
            url += f"q={q}"
        if loc:
            url += f"&l={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".result, .person, .search-result, [class*='listing']")
            logger.info(f"Found {len(cards)} cards on ZabaSearch")
            
            for card in cards:  # Process ALL cards
                try:
                    name_el = card.query_selector("h2, h3, .name, [class*='name']")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".address, .location")
                    addr_text = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector(".phone, [class*='phone']")
                    phone_text = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone_text:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone_text = pcs[0] if pcs else ""
                    
                    if phone_text and name_text:
                        results.append(_standard_result(phone_text, name_text, addr_text, "zabasearch"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"ZabaSearch extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_yellowpages(keywords, location):
    """Scrape YellowPages for business information - UNLIMITED RESULTS"""
    logger.info(f"🟡 Starting YellowPages scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.yellowpages.com/search?search_terms={q}&geo_location_terms={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".result, .search-result, .business-result, .srp-listing")
            if not cards:
                cards = page.query_selector_all("[data-analytics='listing']")
                
            logger.info(f"Found {len(cards)} cards on YellowPages")
            
            # Process ALL cards - NO LIMIT
            for card in cards:
                try:
                    name_el = card.query_selector("a.business-name, h2 a, .business-name")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".street-address, .address, .adr, [class*='address']")
                    addr_text = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector("a.phone, .phones, .phone-number, [class*='phone']")
                    phone_text = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone_text:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone_text = pcs[0] if pcs else ""
                    
                    if phone_text and name_text:
                        results.append(_standard_result(phone_text, name_text, addr_text, "yellowpages"))
                        logger.info(f"✅ Found: {name_text} - {phone_text}")
                        
                except Exception as e:
                    continue
                    
        except Exception as e:
            logger.error(f"YellowPages extraction error: {e}")
            
        if not results:
            phones = extract_phone_from_page(page)
            for p in phones[:10]:
                results.append(_standard_result(p, page.title() or "N/A", "", "yellowpages-fallback"))
                
        logger.info(f"YellowPages returning {len(results)} results")
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_whitepages(keywords, location):
    """Scrape WhitePages for business information - UNLIMITED RESULTS"""
    logger.info(f"⚪ Starting WhitePages scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.whitepages.com/business/{q}/{loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".card, .listing-card, .result, .business-card")
            logger.info(f"Found {len(cards)} cards on WhitePages")
            
            for card in cards:  # Process ALL cards
                try:
                    name_el = card.query_selector(".name, .business-name, h2, h3")
                    name = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".address, .street-address, .location")
                    addr = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector("a[href^='tel:'], .phone, .phone-number")
                    phone = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone = pcs[0] if pcs else ""
                    
                    if phone and name:
                        results.append(_standard_result(phone, name, addr, "whitepages"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"WhitePages extraction error: {e}")
            
        if not results:
            phones = extract_phone_from_page(page)
            for p in phones[:10]:
                results.append(_standard_result(p, page.title() or "N/A", "", "whitepages-fallback"))
                
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_manta(keywords, location):
    """Scrape Manta for business information - UNLIMITED RESULTS"""
    logger.info(f"🔵 Starting Manta scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.manta.com/search?search={q}&search_location={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".result, .listing, .business-card, .search-result")
            logger.info(f"Found {len(cards)} cards on Manta")
            
            for card in cards:  # Process ALL cards
                try:
                    name_el = card.query_selector("h2, h3, a, .business-name")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".address, .location, [class*='address']")
                    addr = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector("a.phone, .phone, .telephone")
                    phone_text = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone_text:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone_text = pcs[0] if pcs else ""
                    
                    if phone_text and name_text:
                        results.append(_standard_result(phone_text, name_text, addr, "manta"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"Manta extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def safe_scrape_yelp(keywords, location):
    """Scrape Yelp for business information - UNLIMITED RESULTS"""
    logger.info(f"🔴 Starting Yelp scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    url = f"https://www.yelp.com/search?find_desc={q}&find_loc={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all("article, .business-listing, .search-result, [class*='business']")
            logger.info(f"Found {len(cards)} cards on Yelp")
            
            for card in cards:  # Process ALL cards
                try:
                    name_el = card.query_selector("h3, h4, a, [class*='business']")
                    name = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector("address, .address, [class*='address']")
                    addr = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_candidates = extract_phone_candidates(card.inner_text())
                    phone = phone_candidates[0] if phone_candidates else ""
                    
                    if phone and name:
                        results.append(_standard_result(phone, name, addr, "yelp"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"Yelp extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

# Export all scrapers
__all__ = [
    'scrape_truepeoplesearch',
    'scrape_spokeo', 
    'scrape_fastpeoplesearch',
    'scrape_zabasearch',
    'scrape_yellowpages',
    'scrape_whitepages',
    'scrape_manta',
    'safe_scrape_yelp'
]

logger.info("✅ All enhanced scrapers defined and ready")