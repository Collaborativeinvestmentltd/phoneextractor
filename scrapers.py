# scrapers.py - FIXED VERSION
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
logger = logging.getLogger("scrapers")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Try to import Playwright with better error handling
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
    PLAYWRIGHT_AVAILABLE = True
    logger.info("✅ Playwright successfully imported")
except ImportError as e:
    logger.error(f"❌ Playwright import failed: {e}")
    PLAYWRIGHT_AVAILABLE = False

# Proxy pool env var
PROXY_POOL = [p.strip() for p in os.environ.get("PROXY_POOL", "").split(",") if p.strip()]
PLAYWRIGHT_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() not in ("0", "false", "no")

# User agents
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

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

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

def click_if_visible(page, selector, timeout=1500):
    try:
        element = page.query_selector(selector)
        if element:
            box = element.bounding_box()
            if box:
                element.scroll_into_view_if_needed()
                human_wait(0.05, 0.18)
                element.click(timeout=timeout)
                human_wait(0.15, 0.4)
                return True
    except Exception:
        return False
    return False

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

# Mock browser function for fallback
def _mock_browser_and_run(func, proxy=None, headless=True, timeout_ms=30000):
    logger.warning("Using mock browser - Playwright not available or failed")
    time.sleep(2)
    return [{
        'number': f"555-{int(time.time()) % 10000:04d}",
        'name': f'Sample Business {int(time.time()) % 1000}',
        'address': f'123 Main St, Sample City',
        'source': 'mock'
    }]

# Real browser function
def _launch_browser_and_run(func, proxy=None, headless=PLAYWRIGHT_HEADLESS, timeout_ms=30000):
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available - using mock")
        return _mock_browser_and_run(func, proxy, headless, timeout_ms)
    
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

    # 1) tel: links
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

    # 2) phone elements
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

    # 3) click reveal buttons
    click_selectors = [
        "button:has-text('Show number')",
        "button:has-text('Show phone')",
        "button:has-text('Reveal phone')",
        ".show-phone, .reveal-phone, .phone-reveal"
    ]
    for sel in click_selectors:
        try:
            clicked = click_if_visible(page, sel)
            if clicked:
                human_wait(0.25, 0.9)
                body = page.content()
                candidates.extend(extract_phone_candidates(body))
        except Exception:
            continue

    # 4) script tags
    try:
        scripts = page.query_selector_all("script[type='application/ld+json'], script")
        for s in scripts:
            try:
                txt = s.inner_text() or ""
                if len(txt) < 10:
                    continue
                candidates.extend(extract_phone_candidates(txt))
            except Exception:
                continue
    except Exception:
        pass

    # 5) full page text
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

def _standard_result(number, name, address, source):
    return {
        "number": number or "N/A",
        "name": normalize_text(name) or "N/A",
        "address": normalize_text(address) or "N/A",
        "source": source,
        "timestamp": utc_now_iso()
    }

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
def scrape_yellowpages(keywords, location):
    logger.info(f"🟡 Starting YellowPages scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.yellowpages.com/search?search_terms={q}&geo_location_terms={loc}"

    def extractor(page, html):
        results = []
        try:
            # Try multiple selectors for YellowPages
            cards = page.query_selector_all(".result, .search-result, .business-result, .srp-listing")
            if not cards:
                cards = page.query_selector_all("[data-analytics='listing']")
                
            logger.info(f"Found {len(cards)} cards on YellowPages")
            
            for card in cards[:20]:
                try:
                    # Name
                    name_el = card.query_selector("a.business-name, h2 a, .business-name")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    # Address
                    addr_el = card.query_selector(".street-address, .address, .adr, [class*='address']")
                    addr_text = addr_el.inner_text().strip() if addr_el else ""
                    
                    # Phone
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
    logger.info(f"⚪ Starting WhitePages scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.whitepages.com/business/{q}/{loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".card, .listing-card, .result, .business-card")
            logger.info(f"Found {len(cards)} cards on WhitePages")
            
            for card in cards[:20]:
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
    logger.info(f"🔵 Starting Manta scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.manta.com/search?search={q}&search_location={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".result, .listing, .business-card, .search-result")
            logger.info(f"Found {len(cards)} cards on Manta")
            
            for card in cards[:20]:
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
    logger.info(f"🔴 Starting Yelp scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    url = f"https://www.yelp.com/search?find_desc={q}&find_loc={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all("article, .business-listing, .search-result, [class*='business']")
            logger.info(f"Found {len(cards)} cards on Yelp")
            
            for card in cards[:15]:
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

@retry(max_retries=2, delay_seconds=2)
def scrape_411(keywords, location):
    logger.info(f"🟣 Starting 411 scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.411.com/business/{q}/{loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".result, .listing, .business-card")
            logger.info(f"Found {len(cards)} cards on 411")
            
            for card in cards[:20]:
                try:
                    name_el = card.query_selector("h2, h3, a, .name")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".address, .location, [class*='address']")
                    addr = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector("a[href^='tel:'], .phone, .telephone")
                    phone = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone:
                        pcs = extract_phone_candidates(card.inner_text())
                        phone = pcs[0] if pcs else ""
                    
                    if phone and name_text:
                        results.append(_standard_result(phone, name_text, addr, "411.com"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"411 extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_local_com(keywords, location):
    logger.info(f"🟢 Starting Local.com scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.local.com/business/results/?keyword={q}&location={loc}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".listing, .result, .business-card")
            logger.info(f"Found {len(cards)} cards on Local.com")
            
            for card in cards[:20]:
                try:
                    name_el = card.query_selector("h2, h3, a, .title")
                    name_text = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".address, .location")
                    addr = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_el = card.query_selector(".phone, .contact-phone, a[href^='tel:']")
                    phone = phone_el.inner_text().strip() if phone_el else ""
                    
                    if not phone:
                        pcs = extract_phone_candidates(card.inner_text())
                        phone = pcs[0] if pcs else ""
                    
                    if phone and name_text:
                        results.append(_standard_result(phone, name_text, addr, "local.com"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"Local.com extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def safe_scrape_foursquare(keywords, location):
    logger.info(f"🟠 Starting Foursquare scrape for '{keywords}' in '{location}'")
    q = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    url = f"https://foursquare.com/explore?mode=url&near={loc}&q={q}"

    def extractor(page, html):
        results = []
        try:
            cards = page.query_selector_all(".venue, .result, .venue-card")
            logger.info(f"Found {len(cards)} cards on Foursquare")
            
            for card in cards[:15]:
                try:
                    name_el = card.query_selector("h2, h3, a, .venueName")
                    name = name_el.inner_text().strip() if name_el else ""
                    
                    addr_el = card.query_selector(".venueAddress, .address, .location")
                    addr = addr_el.inner_text().strip() if addr_el else ""
                    
                    phone_candidates = extract_phone_candidates(card.inner_text())
                    phone = phone_candidates[0] if phone_candidates else ""
                    
                    if phone and name:
                        results.append(_standard_result(phone, name, addr, "foursquare"))
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"Foursquare extraction error: {e}")
            
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

# Export the scrapers
__all__ = [
    'scrape_yellowpages',
    'scrape_whitepages', 
    'scrape_manta',
    'scrape_411',
    'scrape_local_com',
    'safe_scrape_yelp',
    'safe_scrape_foursquare'
]

logger.info("✅ All scrapers defined and ready")