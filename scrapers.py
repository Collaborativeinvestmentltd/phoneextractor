import random
import logging
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from functools import wraps
import time
from datetime import datetime, timezone

# Set up logger for scrapers
logger = logging.getLogger("scrapers")

# -----------------------
# Error Handling Decorator
# -----------------------
def scraper_error_handler(max_retries=2, delay=2):
    def decorator(scraper_func):
        @wraps(scraper_func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return scraper_func(*args, **kwargs)
                except PlaywrightTimeoutError as e:
                    logger.warning(f"Timeout on attempt {attempt + 1} for {scraper_func.__name__}: {e}")
                    if attempt < max_retries:
                        time.sleep(delay * (attempt + 1))
                        continue
                    logger.error(f"Max retries exceeded for {scraper_func.__name__}: {e}")
                    return []
                except Exception as e:
                    logger.error(f"Error in {scraper_func.__name__} on attempt {attempt + 1}: {e}")
                    if attempt < max_retries:
                        time.sleep(delay * (attempt + 1))
                        continue
                    return []
            return []
        return wrapper
    return decorator

# -----------------------
# Phone Number Validation
# -----------------------
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

# -----------------------
# Proxy Manager
# -----------------------
def load_proxies(filename="proxies.txt"):
    try:
        with open(filename, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
            logger.info(f"Loaded {len(proxies)} proxies from {filename}")
            return proxies
    except FileNotFoundError:
        logger.warning("proxies.txt not found, running without proxy")
        return []
    except Exception as e:
        logger.error(f"Error loading proxies: {e}")
        return []

PROXIES = load_proxies()

def get_random_proxy():
    return random.choice(PROXIES) if PROXIES else None

# -----------------------
# Browser Launcher
# -----------------------
def launch_browser(playwright, headless=True, timeout=60000):
    proxy = get_random_proxy()
    try:
        launch_options = {
            "headless": headless, 
            "timeout": timeout,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        }
        
        if proxy:
            logger.info(f"Using proxy: {proxy}")
            launch_options["proxy"] = {"server": proxy}

        browser = playwright.chromium.launch(**launch_options)
        return browser

    except Exception as e:
        logger.error(f"Failed to launch browser: {e}")
        # Fallback without proxy
        try:
            return playwright.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage"
                ]
            )
        except Exception as e2:
            logger.error(f"Fallback browser launch also failed: {e2}")
            return None

# -----------------------
# Helper for timestamps
# -----------------------
def utc_now():
    return datetime.now(timezone.utc).isoformat()

# -----------------------
# Safe Text Extraction
# -----------------------
def safe_extract_text(element, selector=None):
    """Safely extract text from an element"""
    try:
        if selector:
            element = element.query_selector(selector)
        if element:
            text = element.inner_text().strip()
            return text if text else "N/A"
        return "N/A"
    except:
        return "N/A"

# -----------------------
# SCRAPERS WITH CORRECTED SELECTORS
# -----------------------

@scraper_error_handler(max_retries=2)
def scrape_yellowpages(keywords, location):
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        if not browser:
            return results
            
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        try:
            query = "+".join(keywords.split()) if keywords else "business"
            loc = "+".join(location.split()) if location else "usa"
            url = f"https://www.yellowpages.com/search?search_terms={query}&geo_location_terms={loc}"
            logger.info(f"Scraping YellowPages: {url}")

            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            # Wait for results with multiple possible selectors
            try:
                page.wait_for_selector("div.result, div.search-result, div.listing", timeout=30000)
            except:
                logger.warning("No results found on YellowPages")
                return results
            
            cards = page.query_selector_all("div.result, div.search-result, div.listing")
            logger.info(f"Found {len(cards)} results on YellowPages")

            for card in cards[:20]:
                try:
                    # Extract phone number using multiple selectors
                    phone_text = "N/A"
                    for selector in ["div.phones", "li.phone", ".phone-number", "div.phone", "span.phone"]:
                        phone_element = card.query_selector(selector)
                        if phone_element:
                            phone_text = safe_extract_text(phone_element)
                            break
                    
                    validated_phone = validate_phone_number(phone_text)
                    if not validated_phone:
                        continue
                    
                    # Extract name
                    name_text = "N/A"
                    for selector in ["a.business-name", "h2 a", ".business-name", "span.business-name", "h2"]:
                        name_element = card.query_selector(selector)
                        if name_element:
                            name_text = safe_extract_text(name_element)
                            break
                    
                    # Extract address
                    address_text = "N/A"
                    for selector in ["div.street-address", ".address", "div.adr", "span.address", ".street-address"]:
                        address_element = card.query_selector(selector)
                        if address_element:
                            address_text = safe_extract_text(address_element)
                            break

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
                    
        except Exception as e:
            logger.error(f"Error in YellowPages scraper: {e}")
        finally:
            try:
                context.close()
                browser.close()
            except:
                pass
    
    logger.info(f"YellowPages scraper returning {len(results)} valid results")
    return results

@scraper_error_handler(max_retries=2)
def scrape_whitepages(keywords, location):
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        if not browser:
            return results
            
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        try:
            query = "+".join(keywords.split()) if keywords else "business"
            loc = "+".join(location.split()) if location else "usa"
            url = f"https://www.whitepages.com/business/{query}/{loc}"
            logger.info(f"Scraping WhitePages: {url}")

            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            try:
                page.wait_for_selector("div.card, div.result, div.listing", timeout=30000)
            except:
                logger.warning("No results found on WhitePages")
                return results
            
            cards = page.query_selector_all("div.card, div.result, div.listing")
            logger.info(f"Found {len(cards)} results on WhitePages")

            for card in cards[:15]:
                try:
                    # Phone number
                    phone_text = "N/A"
                    for selector in ["div.phone", "span.phone", ".phone-number", ".tel"]:
                        phone_element = card.query_selector(selector)
                        if phone_element:
                            phone_text = safe_extract_text(phone_element)
                            break
                    
                    validated_phone = validate_phone_number(phone_text)
                    if not validated_phone:
                        continue
                    
                    # Name
                    name_text = "N/A"
                    for selector in ["h2", ".name", ".business-name", "h3"]:
                        name_element = card.query_selector(selector)
                        if name_element:
                            name_text = safe_extract_text(name_element)
                            break
                    
                    # Address
                    address_text = "N/A"
                    for selector in [".address", ".location", ".street-address", ".adr"]:
                        address_element = card.query_selector(selector)
                        if address_element:
                            address_text = safe_extract_text(address_element)
                            break

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
                    
        except Exception as e:
            logger.error(f"Error in WhitePages scraper: {e}")
        finally:
            try:
                context.close()
                browser.close()
            except:
                pass
    
    return results

@scraper_error_handler(max_retries=2)
def scrape_manta(keywords, location):
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        if not browser:
            return results
            
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        try:
            query = "+".join(keywords.split()) if keywords else "business"
            loc = "+".join(location.split()) if location else "usa"
            url = f"https://www.manta.com/search?search={query}&search_location={loc}"
            logger.info(f"Scraping Manta: {url}")

            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            try:
                page.wait_for_selector("div[data-tn='listing-card'], div.card, div.result", timeout=30000)
            except:
                logger.warning("No results found on Manta")
                return results
            
            cards = page.query_selector_all("div[data-tn='listing-card'], div.card, div.result")
            logger.info(f"Found {len(cards)} results on Manta")

            for card in cards[:15]:
                try:
                    # Phone number
                    phone_text = "N/A"
                    for selector in ["a[data-tn='listing-phone']", ".phone", ".phone-number", "span.phone"]:
                        phone_element = card.query_selector(selector)
                        if phone_element:
                            phone_text = safe_extract_text(phone_element)
                            break
                    
                    validated_phone = validate_phone_number(phone_text)
                    if not validated_phone:
                        continue
                    
                    # Name
                    name_text = "N/A"
                    for selector in ["h2", ".business-name", "[data-tn='business-name']", "h3"]:
                        name_element = card.query_selector(selector)
                        if name_element:
                            name_text = safe_extract_text(name_element)
                            break
                    
                    # Address
                    address_text = "N/A"
                    for selector in [".address", ".location", "[data-tn='listing-address']", ".street-address"]:
                        address_element = card.query_selector(selector)
                        if address_element:
                            address_text = safe_extract_text(address_element)
                            break

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
                    
        except Exception as e:
            logger.error(f"Error in Manta scraper: {e}")
        finally:
            try:
                context.close()
                browser.close()
            except:
                pass
    
    return results

@scraper_error_handler(max_retries=2)
def safe_scrape_yelp(keywords, location):
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        if not browser:
            return results
            
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        try:
            query = "+".join(keywords.split()) if keywords else "restaurant"
            loc = "+".join(location.split()) if location else "usa"
            url = f"https://www.yelp.com/search?find_desc={query}&find_loc={loc}"
            logger.info(f"Scraping Yelp: {url}")

            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            try:
                page.wait_for_selector('[data-testid="serp-ia-card"], div.business, div.listing', timeout=30000)
            except:
                logger.warning("No results found on Yelp")
                return results
            
            cards = page.query_selector_all('[data-testid="serp-ia-card"], div.business, div.listing')
            logger.info(f"Found {len(cards)} results on Yelp")

            for card in cards[:15]:
                try:
                    # Yelp typically requires interaction for phone numbers
                    phone_text = "N/A"
                    
                    # Name
                    name_text = "N/A"
                    for selector in ["h3", "h4", ".business-name", "a"]:
                        name_element = card.query_selector(selector)
                        if name_element:
                            name_text = safe_extract_text(name_element)
                            if name_text and name_text != "N/A":
                                break
                    
                    # Address
                    address_text = "N/A"
                    for selector in ["address", ".address", ".street-address"]:
                        address_element = card.query_selector(selector)
                        if address_element:
                            address_text = safe_extract_text(address_element)
                            break

                    # For Yelp, return results even without phone numbers
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
                    
        except Exception as e:
            logger.error(f"Error in Yelp scraper: {e}")
        finally:
            try:
                context.close()
                browser.close()
            except:
                pass
    
    return results

@scraper_error_handler(max_retries=2)
def scrape_411(keywords, location):
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        if not browser:
            return results
            
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        try:
            query = "+".join(keywords.split()) if keywords else "business"
            loc = "+".join(location.split()) if location else "usa"
            url = f"https://www.411.com/business/{query}/{loc}"
            logger.info(f"Scraping 411.com: {url}")

            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            try:
                page.wait_for_selector("div.result, div.card, div.listing", timeout=30000)
            except:
                logger.warning("No results found on 411.com")
                return results
            
            cards = page.query_selector_all("div.result, div.card, div.listing")
            logger.info(f"Found {len(cards)} results on 411.com")

            for card in cards[:15]:
                try:
                    # Phone number
                    phone_text = "N/A"
                    for selector in [".phone", ".phone-number", ".tel", "span.phone"]:
                        phone_element = card.query_selector(selector)
                        if phone_element:
                            phone_text = safe_extract_text(phone_element)
                            break
                    
                    validated_phone = validate_phone_number(phone_text)
                    if not validated_phone:
                        continue
                    
                    # Name
                    name_text = "N/A"
                    for selector in ["h2", ".name", ".business-name", "h3"]:
                        name_element = card.query_selector(selector)
                        if name_element:
                            name_text = safe_extract_text(name_element)
                            break
                    
                    # Address
                    address_text = "N/A"
                    for selector in [".address", ".location", ".street-address"]:
                        address_element = card.query_selector(selector)
                        if address_element:
                            address_text = safe_extract_text(address_element)
                            break

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
                    
        except Exception as e:
            logger.error(f"Error in 411.com scraper: {e}")
        finally:
            try:
                context.close()
                browser.close()
            except:
                pass
    
    return results

@scraper_error_handler(max_retries=2)
def scrape_local_com(keywords, location):
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        if not browser:
            return results
            
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        try:
            query = "+".join(keywords.split()) if keywords else "business"
            loc = "+".join(location.split()) if location else "usa"
            url = f"https://www.local.com/business/results/?keyword={query}&location={loc}"
            logger.info(f"Scraping Local.com: {url}")

            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            try:
                page.wait_for_selector("div.listing, div.result, div.card", timeout=30000)
            except:
                logger.warning("No results found on Local.com")
                return results
            
            cards = page.query_selector_all("div.listing, div.result, div.card")
            logger.info(f"Found {len(cards)} results on Local.com")

            for card in cards[:15]:
                try:
                    # Phone number
                    phone_text = "N/A"
                    for selector in [".phone", ".phone-number", ".contact-phone", "span.phone"]:
                        phone_element = card.query_selector(selector)
                        if phone_element:
                            phone_text = safe_extract_text(phone_element)
                            break
                    
                    validated_phone = validate_phone_number(phone_text)
                    if not validated_phone:
                        continue
                    
                    # Name
                    name_text = "N/A"
                    for selector in ["h2", ".business-name", ".title", "h3"]:
                        name_element = card.query_selector(selector)
                        if name_element:
                            name_text = safe_extract_text(name_element)
                            break
                    
                    # Address
                    address_text = "N/A"
                    for selector in [".address", ".location", ".street-address"]:
                        address_element = card.query_selector(selector)
                        if address_element:
                            address_text = safe_extract_text(address_element)
                            break

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
                    
        except Exception as e:
            logger.error(f"Error in Local.com scraper: {e}")
        finally:
            try:
                context.close()
                browser.close()
            except:
                pass
    
    return results

@scraper_error_handler(max_retries=2)
def safe_scrape_foursquare(keywords, location):
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        if not browser:
            return results
            
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        try:
            query = "+".join(keywords.split()) if keywords else "restaurant"
            loc = "+".join(location.split()) if location else "usa"
            url = f"https://foursquare.com/explore?mode=url&near={loc}&q={query}"
            logger.info(f"Scraping Foursquare: {url}")

            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            try:
                page.wait_for_selector("div.venue, div.result, div.card", timeout=30000)
            except:
                logger.warning("No results found on Foursquare")
                return results
            
            cards = page.query_selector_all("div.venue, div.result, div.card")
            logger.info(f"Found {len(cards)} results on Foursquare")

            for card in cards[:10]:
                try:
                    # Foursquare typically doesn't show phone numbers easily
                    phone_text = "N/A"
                    
                    # Name
                    name_text = "N/A"
                    for selector in ["h2", ".venueName", ".name", "h3"]:
                        name_element = card.query_selector(selector)
                        if name_element:
                            name_text = safe_extract_text(name_element)
                            break
                    
                    # Address
                    address_text = "N/A"
                    for selector in [".venueAddress", ".address", ".location", ".street-address"]:
                        address_element = card.query_selector(selector)
                        if address_element:
                            address_text = safe_extract_text(address_element)
                            break

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
                    
        except Exception as e:
            logger.error(f"Error in Foursquare scraper: {e}")
        finally:
            try:
                context.close()
                browser.close()
            except:
                pass
    
    return results