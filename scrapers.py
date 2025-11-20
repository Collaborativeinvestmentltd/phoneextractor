# scrapers.py
import os
import re
import time
import random
import logging
from datetime import datetime, timezone
from urllib.parse import quote
from functools import wraps
from typing import List, Dict, Optional

# Playwright sync API
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[WARN] Playwright not available - using mock scrapers")

logger = logging.getLogger("scrapers")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Proxy pool env var (comma separated, examples:)
# http://user:pass@host:port or http://host:port or socks5://host:port
PROXY_POOL = [p.strip() for p in os.environ.get("PROXY_POOL", "").split(",") if p.strip()]
# Headless toggles
PLAYWRIGHT_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() not in ("0", "false", "no")

# Basic user agents for extra rotation (Playwright sets UA, but we still vary)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
]

# Utility: safe retry decorator
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
                    time.sleep(delay_seconds * (attempt + 1))
            logger.error(f"[retry] {fn.__name__} exceeded retries: {last_exc}")
            return []
        return wrapper
    return deco

# Helpers ---------------------------------------------------

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def choose_proxy() -> Optional[Dict]:
    """Return a proxy dict suitable for playwright 'proxy' param, or None if no proxies configured."""
    if not PROXY_POOL:
        return None
    raw = random.choice(PROXY_POOL)
    # playwright expects: {"server": "http://host:port", "username": "...", "password": "..."}
    # Support http://user:pass@host:port or http://host:port
    m = re.match(r'(?P<scheme>https?|socks5(?:h)?):\/\/(?:(?P<user>[^:@]+)(?::(?P<pw>[^@]+))?@)?(?P<host>[^:\/]+):(?P<port>\d+)', raw)
    if not m:
        # If not matching, return as server only
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
// small stealth modifications for navigator
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
    # digits contains only digits (maybe leading country code)
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    # fallback
    return digits

def extract_phone_candidates(text: str) -> List[str]:
    candidates = PHONE_REGEX.findall(text or "")
    cleaned = []
    for c in candidates:
        # Remove non-digits except keep ext as xNNN
        digits = re.sub(r'\D', '', c)
        if len(digits) >= 10:
            # take last 10 or 11
            if len(digits) > 11:
                digits = digits[-10:]
            cleaned.append(format_phone(digits))
    return list(dict.fromkeys(cleaned))  # preserve order, unique

def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r'\s+', ' ', s).strip()

# Mock browser function when Playwright is not available
def _mock_browser_and_run(func, proxy=None, headless=True, timeout_ms=30000):
    """Mock browser function for when Playwright is not available"""
    logger.warning("Using mock browser - Playwright not available")
    time.sleep(2)
    return [{
        'number': f"555-{int(time.time()) % 10000:04d}",
        'name': f'Sample Business {int(time.time()) % 1000}',
        'address': f'123 Main St, Sample City',
        'source': 'mock'
    }]

# Core Playwright page fetch + extraction utilities ------------------------

def _launch_browser_and_run(func, proxy=None, headless=PLAYWRIGHT_HEADLESS, timeout_ms=30000):
    """Launch a short-lived browser, run func(page) and return the result."""
    if not PLAYWRIGHT_AVAILABLE:
        return _mock_browser_and_run(func, proxy, headless, timeout_ms)
        
    try:
        with sync_playwright() as p:
            # Use chromium for best compatibility
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

            browser = p.chromium.launch(**launch_args)
            ua = random.choice(USER_AGENTS)
            context_args = {
                "user_agent": ua,
                "viewport": {"width": 1280 + random.randint(-50, 50), "height": 720 + random.randint(-50, 50)},
                "locale": "en-US",
                "timezone_id": "America/New_York"
            }
            context = browser.new_context(**context_args)
            page = context.new_page()
            # small stealth
            try:
                page.add_init_script(STEALTH_SCRIPT)
            except Exception:
                pass

            # run user function
            result = func(page, context, browser)
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            return result
    except PlaywrightError as e:
        logger.warning(f"Playwright error: {e}")
        return []
    except Exception as e:
        logger.error(f"Browser launch/run error: {e}")
        return []

def safe_visit_and_get_html(page, url, wait_selector=None, timeout=15000):
    """Visit url and try to wait for content. Returns page content text."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout while loading: {url}")
    except Exception as e:
        logger.warning(f"Error visiting {url}: {e}")
        # continue to read whatever loaded

    # If wait_selector provided, wait a bit for dynamic content
    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, timeout=5000)
        except Exception:
            pass

    # small human pause
    human_wait(0.1, 0.45)
    # return HTML
    try:
        return page.content()
    except Exception:
        return page.inner_text("body") or ""

def extract_phone_from_page(page) -> List[str]:
    """Aggressive phone extraction from page object."""
    candidates = []

    # 1) look for tel: links
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
                # also try inner text
                found = extract_phone_candidates(text)
                candidates.extend(found)
            except Exception:
                continue
    except Exception:
        pass

    # 2) common data attributes and spans
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

    # 3) try clicking "Show number" or similar buttons
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

    # 4) inspect script tags / initial state JSON
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

    # 5) full page text fallback
    try:
        body_text = page.inner_text("body") or ""
        candidates.extend(extract_phone_candidates(body_text[:200000]))
    except Exception:
        pass

    # deduplicate and return
    seen = []
    for c in candidates:
        if c not in seen and c:
            seen.append(c)
    return seen

# Platform scrapers (playwright-based)
# Every function returns a list of {number, name, address, source, timestamp}

def _standard_result(number, name, address, source):
    return {
        "number": number or "N/A",
        "name": normalize_text(name) or "N/A",
        "address": normalize_text(address) or "N/A",
        "source": source,
        "timestamp": utc_now_iso()
    }

# Generic wrapper used by each platform implementation
def _run_playwright_scrape(target_url, extractor_func, proxy=None, headless=PLAYWRIGHT_HEADLESS):
    """
    Opens URL in a Playwright page and runs extractor_func(page).
    extractor_func should accept a page and return a list of results (dicts).
    """
    def run(page, context, browser):
        logger.info(f"[playwright] Visiting {target_url} (proxy={'yes' if proxy else 'no'})")
        html = safe_visit_and_get_html(page, target_url, wait_selector=None, timeout=25000)
        # Try immediate extraction
        try:
            res = extractor_func(page, html)
            if res:
                return res
        except Exception as e:
            logger.warning(f"Extractor func error: {e}")

        # If nothing found, try extra interactions / wait
        try:
            human_wait(0.5, 1.2)
            res = extractor_func(page, page.content())
            if res:
                return res
        except Exception:
            pass

        # Final fallback: extract raw phone candidates from page
        try:
            phones = extract_phone_from_page(page)
            results = []
            for p in phones[:25]:
                results.append(_standard_result(p, page.title() or "N/A", "", "fallback"))
            return results
        except Exception:
            return []

    return _launch_browser_and_run(run, proxy=proxy, headless=headless)

# -------------------------
# Individual platform extractor implementations
# -------------------------

@retry(max_retries=2, delay_seconds=2)
def scrape_yellowpages(keywords, location):
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.yellowpages.com/search?search_terms={q}&geo_location_terms={loc}"

    def extractor(page, html):
        results = []
        # Prefer searching for elements via Playwright API
        phone_candidates = extract_phone_from_page(page)

        # Try to iterate result cards
        try:
            cards = page.query_selector_all("div.search-results .result, .search-result, .result")
            if not cards:
                cards = page.query_selector_all("div.result, li.result")
            for card in cards[:30]:
                try:
                    # name
                    name_el = card.query_selector("a.business-name, h2, .business-name")
                    name_text = name_el.inner_text().strip() if name_el else (card.query_selector("h2").inner_text().strip() if card.query_selector("h2") else "")
                    # address
                    addr_el = card.query_selector(".street-address, .address, .adr, .locality")
                    addr_text = addr_el.inner_text().strip() if addr_el else ""
                    # phone
                    phone_el = card.query_selector("a.phone, div.phones, span.phone, .phone")
                    phone_text = ""
                    if phone_el:
                        phone_text = phone_el.inner_text().strip()
                    # fallback: search inside card HTML
                    if not phone_text:
                        inner = card.inner_text()
                        pcs = extract_phone_candidates(inner)
                        phone_text = pcs[0] if pcs else ""

                    if phone_text:
                        results.append(_standard_result(phone_text, name_text, addr_text, "yellowpages"))
                except Exception:
                    continue
        except Exception:
            pass

        # if nothing, use coarse page phones
        if not results:
            for p in phone_candidates[:25]:
                results.append(_standard_result(p, page.title() or "N/A", "", "yellowpages-fallback"))

        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_whitepages(keywords, location):
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.whitepages.com/business/{q}/{loc}"

    def extractor(page, html):
        results = []
        cards = page.query_selector_all("div.card, li.search-result, .result, .listing")
        for card in cards[:25]:
            try:
                name_el = card.query_selector(".name, .business-name, h2, h3")
                name = name_el.inner_text().strip() if name_el else ""
                addr_el = card.query_selector(".address, .street-address, .location")
                addr = addr_el.inner_text().strip() if addr_el else ""
                phone_el = card.query_selector("a[href^='tel:'], .phone, .phone-number, .tel")
                phone = ""
                if phone_el:
                    phone = phone_el.inner_text().strip()
                else:
                    inner = card.inner_text()
                    pcs = extract_phone_candidates(inner)
                    phone = pcs[0] if pcs else ""
                if phone:
                    results.append(_standard_result(phone, name, addr, "whitepages"))
            except Exception:
                continue
        if not results:
            # fallback to scanning page
            phones = extract_phone_from_page(page)
            for p in phones[:20]:
                results.append(_standard_result(p, page.title() or "N/A", "", "whitepages-fallback"))
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_manta(keywords, location):
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.manta.com/search?search={q}&search_location={loc}"

    def extractor(page, html):
        results = []
        cards = page.query_selector_all(".search-results .info, .card, .result, .directory-listing")
        for card in cards[:25]:
            try:
                name = card.query_selector("h2, h3, a") 
                name_text = name.inner_text().strip() if name else ""
                addr_el = card.query_selector(".address, .adr, .locality")
                addr = addr_el.inner_text().strip() if addr_el else ""
                phone_el = card.query_selector("a.phone, .phone, .telephone")
                phone_text = phone_el.inner_text().strip() if phone_el else ""
                if not phone_text:
                    inner = card.inner_text()
                    pcs = extract_phone_candidates(inner)
                    phone_text = pcs[0] if pcs else ""
                if phone_text:
                    results.append(_standard_result(phone_text, name_text, addr, "manta"))
            except Exception:
                continue
        if not results:
            phones = extract_phone_from_page(page)
            for p in phones[:20]:
                results.append(_standard_result(p, page.title() or "N/A", "", "manta-fallback"))
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def safe_scrape_yelp(keywords, location):
    q = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    url = f"https://www.yelp.com/search?find_desc={q}&find_loc={loc}"

    def extractor(page, html):
        results = []
        # Yelp often hides phone numbers. We'll extract names and addresses, and attempt phone via page JSON
        cards = page.query_selector_all(".container__09f24__21w3G .biz-listing, .lemon--div__09f24__1mboc")
        # fallback broad search
        if not cards:
            cards = page.query_selector_all("article, .biz-listing, .lemon--div__09f24__1mboc")
        for card in cards[:25]:
            try:
                name_el = card.query_selector("a.link, h3, h4")
                name = name_el.inner_text().strip() if name_el else ""
                addr_el = card.query_selector("address, .address, .domtags-address")
                addr = addr_el.inner_text().strip() if addr_el else ""
                # phone often missing
                phone_candidates = extract_phone_candidates(card.inner_text())
                phone = phone_candidates[0] if phone_candidates else "N/A"
                results.append(_standard_result(phone, name, addr, "yelp"))
            except Exception:
                continue

        # Try to scan page scripts for phone numbers
        if not results or all(r['number']=="N/A" for r in results):
            phones = extract_phone_from_page(page)
            for p in phones[:30]:
                results.append(_standard_result(p, page.title() or "N/A", "", "yelp-fallback"))

        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_411(keywords, location):
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.411.com/business/{q}/{loc}"

    def extractor(page, html):
        results = []
        cards = page.query_selector_all(".result, .listing, .card")
        for card in cards[:25]:
            try:
                name = card.query_selector("h2, h3, a")
                name_text = name.inner_text().strip() if name else ""
                addr_el = card.query_selector(".address, .location, .adr")
                addr = addr_el.inner_text().strip() if addr_el else ""
                phone_el = card.query_selector("a[href^='tel:'], .phone, .telephone")
                phone = phone_el.inner_text().strip() if phone_el else ""
                if not phone:
                    pcs = extract_phone_candidates(card.inner_text())
                    phone = pcs[0] if pcs else ""
                if phone:
                    results.append(_standard_result(phone, name_text, addr, "411.com"))
            except Exception:
                continue
        if not results:
            phones = extract_phone_from_page(page)
            for p in phones[:20]:
                results.append(_standard_result(p, page.title() or "N/A", "", "411-fallback"))
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def scrape_local_com(keywords, location):
    q = quote(keywords) if keywords else "business"
    loc = quote(location) if location else "usa"
    url = f"https://www.local.com/business/results/?keyword={q}&location={loc}"

    def extractor(page, html):
        results = []
        cards = page.query_selector_all(".listing, .result, .card")
        for card in cards[:25]:
            try:
                name = card.query_selector("h2, h3, a, .title")
                name_text = name.inner_text().strip() if name else ""
                addr_el = card.query_selector(".address, .location")
                addr = addr_el.inner_text().strip() if addr_el else ""
                phone_el = card.query_selector(".phone, .contact-phone, a[href^='tel:']")
                phone = phone_el.inner_text().strip() if phone_el else ""
                if not phone:
                    pcs = extract_phone_candidates(card.inner_text())
                    phone = pcs[0] if pcs else ""
                if phone:
                    results.append(_standard_result(phone, name_text, addr, "local.com"))
            except Exception:
                continue
        if not results:
            phones = extract_phone_from_page(page)
            for p in phones[:20]:
                results.append(_standard_result(p, page.title() or "N/A", "", "local-fallback"))
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())

@retry(max_retries=2, delay_seconds=2)
def safe_scrape_foursquare(keywords, location):
    q = quote(keywords) if keywords else "restaurant"
    loc = quote(location) if location else "usa"
    url = f"https://foursquare.com/explore?mode=url&near={loc}&q={q}"

    def extractor(page, html):
        results = []
        # Foursquare often returns JS-driven content; use fallback scanning
        cards = page.query_selector_all(".venue, .result, .card, .venueName")
        for card in cards[:25]:
            try:
                name_el = card.query_selector("h2, h3, a, .venueName")
                name = name_el.inner_text().strip() if name_el else ""
                addr_el = card.query_selector(".venueAddress, .address, .location")
                addr = addr_el.inner_text().strip() if addr_el else ""
                phone_candidates = extract_phone_candidates(card.inner_text())
                phone = phone_candidates[0] if phone_candidates else "N/A"
                results.append(_standard_result(phone, name, addr, "foursquare"))
            except Exception:
                continue
        if not results:
            phones = extract_phone_from_page(page)
            for p in phones[:15]:
                results.append(_standard_result(p, page.title() or "N/A", "", "foursquare-fallback"))
        return results

    return _run_playwright_scrape(url, extractor_func=extractor, proxy=choose_proxy())