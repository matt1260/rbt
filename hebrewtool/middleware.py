"""
Rate limiting and bot protection middleware.

Prevents bot flooding by implementing IP-based rate limiting
and User-Agent filtering for suspicious crawlers.
"""

import ipaddress
import re
import time
import logging
from django.http import HttpResponse, JsonResponse
from django.core import signing
from django.core.cache import InvalidCacheBackendError, cache, caches
from django.conf import settings
import traceback

logger = logging.getLogger(__name__)

HUMAN_COOKIE_SALT = 'hebrewtool.human_verified'

# Solving the challenge needs no proof of work, so it can only stretch a limit, never lift it.
HUMAN_VERIFIED_LIMIT_MULTIPLIER = 5

LOGIN_PATHS = ('/accounts/login/', '/admin/login/')


def _forwarded_chain(request):
    """The IP addresses in X-Forwarded-For, left to right, skipping anything that isn't one."""
    chain = []
    for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            ipaddress.ip_address(part)
        except ValueError:
            continue
        chain.append(part)
    return chain


def client_ip(request):
    """The IP a request is limited and banned by.

    Each proxy in front of us appends the address it accepted the connection from to
    X-Forwarded-For, so with TRUSTED_PROXY_DEPTH set to the number of entries they add
    between them, the client is that many from the right. Anything further left was
    sent by the client itself and can say whatever it likes. Depth 0 takes the leftmost
    value: forgeable, so a swarm can rotate it and never be limited.
    """
    chain = _forwarded_chain(request)
    depth = getattr(settings, 'TRUSTED_PROXY_DEPTH', 0)
    if depth > 0:
        if len(chain) >= depth:
            return chain[-depth]
        return request.META.get('REMOTE_ADDR')
    if chain:
        return chain[0]
    return request.META.get('REMOTE_ADDR')


def _proxy_chain_for_log(request):
    """What the proxies handed us, for working out TRUSTED_PROXY_DEPTH from the logs."""
    clean = lambda value: (value or '-').replace('\r', ' ').replace('\n', ' ')[:200]
    return (f"xff={clean(request.META.get('HTTP_X_FORWARDED_FOR'))} "
            f"remote={clean(request.META.get('REMOTE_ADDR'))} "
            f"envoy_external={clean(request.META.get('HTTP_X_ENVOY_EXTERNAL_ADDRESS'))} "
            f"real_ip={clean(request.META.get('HTTP_X_REAL_IP'))}")


def _counter_cache():
    """Per-process memory for request counters (CACHES['ratelimit']); the default cache
    where that alias isn't configured, such as under test overrides."""
    try:
        return caches['ratelimit']
    except InvalidCacheBackendError:
        return cache


class RateLimitMiddleware:
    """
    Rate limit requests by IP address to prevent bot flooding.
    
    Limits:
    - 60 requests per minute per IP for verse endpoints
    - 120 requests per minute per IP for chapter endpoints
    - 30 requests per minute per IP for all other endpoints
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def get_client_ip(self, request):
        return client_ip(request)

    def has_human_cookie(self, request, ip):
        human_cookie = request.COOKIES.get('human_verified')
        if not human_cookie:
            return False
        try:
            token = signing.loads(human_cookie, salt=HUMAN_COOKIE_SALT, max_age=24 * 3600)
        except signing.BadSignature:
            return False
        return token.get('ip') == ip

    def __call__(self, request):
        # Skip rate limiting for authenticated users (editors)
        if hasattr(request, 'user') and request.user.is_authenticated:
            return self.get_response(request)
        
        # Skip rate limiting in DEBUG mode for local development
        if getattr(settings, 'DEBUG', False):
            return self.get_response(request)

        # Skip rate limiting for static/media and common benign endpoints (assets, health checks)
        path = request.path or ''
        static_prefix = getattr(settings, 'STATIC_URL', '/static/')
        if path.startswith(static_prefix) or path.startswith('/media/') or path in ('/favicon.ico', '/robots.txt', '/health'):
            return self.get_response(request)

        # Skip rate limiting for the translation status poll to avoid accidental bans
        if path.startswith('/api/translation/status'):
            return self.get_response(request)

        # The inline chapter editor autosaves and prefetches interlinear data on hover, and the
        # Paraphrase Studio polls while generating; both would trip the verse/API limits.
        # These endpoints are staff-only (403 otherwise),
        # and request.user isn't populated yet at this point in the middleware stack.
        if '/api/chapter-editor/' in path or '/api/paraphrase/' in path:
            return self.get_response(request)
        
        ip = self.get_client_ip(request)
        path = request.path
        human_verified = self.has_human_cookie(request, ip)
        
        # Check if IP is banned
        ban_key = f'banned:{ip}'
        try:
            from search.db_utils import safe_cache_get
            ban_data = safe_cache_get(ban_key, None)
        except Exception:
            # Fallback to direct cache access if helper import fails
            try:
                ban_data = cache.get(ban_key)
            except Exception as e:
                logger.exception('Cache get failed for ban_key: %s', e)
                try:
                    from django.db import connection
                    connection.rollback()
                except Exception:
                    pass
                ban_data = None

        if ban_data:
            ban_until = ban_data.get('until', 0)
            if time.time() < ban_until:
                retry_after = int(ban_until - time.time())
                logger.warning(f"[BOT BLOCKED] IP {ip} is banned until {ban_until} (reason: {ban_data.get('reason', 'unknown')})")
                response = HttpResponse(
                    f'Your IP has been temporarily blocked due to excessive requests.\n'
                    f'Try again in {retry_after} seconds.\n'
                    f'Contact the site administrator if you believe this is an error.',
                    status=403,
                    content_type='text/plain'
                )
                response['Retry-After'] = str(retry_after)
                return response
        
        # Determine rate limit based on endpoint
        if request.method == 'POST' and path in LOGIN_PATHS:
            # Password attempts. First, so query params can't move a login into a looser bucket.
            limit = getattr(settings, 'RATE_LIMIT_LOGIN_LIMIT', 10)
            window = getattr(settings, 'RATE_LIMIT_LOGIN_WINDOW', 60)
            endpoint_type = 'login'
            max_strikes = getattr(settings, 'RATE_LIMIT_LOGIN_MAX_STRIKES', 3)
            ban_duration = getattr(settings, 'RATE_LIMIT_LOGIN_BAN_DURATION', 3600)
        elif 'verse' in request.GET and 'chapter' in request.GET:
            # Individual verse lookup - configurable and less aggressive by default
            limit = getattr(settings, 'RATE_LIMIT_VERSE_LIMIT', 20) # Lowered
            window = getattr(settings, 'RATE_LIMIT_VERSE_WINDOW', 60)
            endpoint_type = 'verse'
            max_strikes = getattr(settings, 'RATE_LIMIT_VERSE_MAX_STRIKES', 2)
            ban_duration = getattr(settings, 'RATE_LIMIT_VERSE_BAN_DURATION', 1800)
        elif 'chapter' in request.GET and 'book' in request.GET:
            # Chapter view
            limit = getattr(settings, 'RATE_LIMIT_CHAPTER_LIMIT', 20) # Lowered significantly
            window = getattr(settings, 'RATE_LIMIT_CHAPTER_WINDOW', 60)
            endpoint_type = 'chapter'
            max_strikes = getattr(settings, 'RATE_LIMIT_CHAPTER_MAX_STRIKES', 2)
            ban_duration = getattr(settings, 'RATE_LIMIT_CHAPTER_BAN_DURATION', 1800)
        elif path.startswith('/translate/') or path.startswith('/api/'):
            # Translation API
            limit = getattr(settings, 'RATE_LIMIT_API_LIMIT', 20)
            window = getattr(settings, 'RATE_LIMIT_API_WINDOW', 60)
            endpoint_type = 'api'
            max_strikes = getattr(settings, 'RATE_LIMIT_API_MAX_STRIKES', 3)
            ban_duration = getattr(settings, 'RATE_LIMIT_API_BAN_DURATION', 3600)
        else:
            # General pages
            limit = getattr(settings, 'RATE_LIMIT_GENERAL_LIMIT', 60) # Lowered from 120
            window = getattr(settings, 'RATE_LIMIT_GENERAL_WINDOW', 60)
            endpoint_type = 'general'
            max_strikes = getattr(settings, 'RATE_LIMIT_GENERAL_MAX_STRIKES', 4)
            ban_duration = getattr(settings, 'RATE_LIMIT_GENERAL_BAN_DURATION', 600)
            
        # Drastically throttle requests coming from known Data Centers/Clouds/Proxies
        try:
            geo_data = cache.get(f'geoip_{ip}')
            if geo_data and geo_data.get('is_bot', False):
                limit = max(1, limit // 5)  # 5x stricter
                max_strikes = 1             # Immediately challenge/ban
        except Exception:
            pass

        # Counters are per worker process, so each worker enforces its share of the limit
        limit = max(1, limit // getattr(settings, 'RATE_LIMIT_PROCESSES', 1))

        if human_verified and endpoint_type != 'login':
            limit *= HUMAN_VERIFIED_LIMIT_MULTIPLIER

        cache_key = f'ratelimit:{endpoint_type}:{ip}'
        strikes_key = f'strikes:{endpoint_type}:{ip}'
        
        # Get current request count and timestamp
        counters = _counter_cache()
        rate_data = counters.get(cache_key)

        if rate_data is None:
            rate_data = {'count': 0, 'reset_time': time.time() + window}
        
        current_time = time.time()
        
        # Reset counter if window has passed
        if current_time >= rate_data['reset_time']:
            rate_data = {'count': 1, 'reset_time': current_time + window}
            counters.set(cache_key, rate_data, window)
        else:
            # Increment counter
            rate_data['count'] += 1
            
            # Check if limit exceeded
            if rate_data['count'] > limit:
                # Add a strike
                try:
                    from search.db_utils import safe_cache_get, safe_cache_set
                    strikes = safe_cache_get(strikes_key, 0) or 0
                    strikes = strikes + 1
                    safe_cache_set(strikes_key, strikes, 7200)
                except Exception:
                    try:
                        strikes = cache.get(strikes_key, 0) + 1
                        cache.set(strikes_key, strikes, 7200)
                    except Exception:
                        logger.exception('Failed to update strikes key in cache')
                        strikes = 1
                
                user_agent = request.META.get('HTTP_USER_AGENT', '')[:200]
                # request.path is percent-decoded, so %0a would forge a line in these logs
                log_path = path.replace('\r', ' ').replace('\n', ' ')
                logger.warning(f"[RATE LIMIT] IP {ip} exceeded {endpoint_type} limit (strike {strikes}/{max_strikes}) UA={user_agent}")
                # Also print to stdout so platform logs capture the IP immediately
                print(f"[RATE_LIMIT] ip={ip} endpoint={endpoint_type} count={rate_data['count']} strikes={strikes} ua={user_agent} path={log_path} {_proxy_chain_for_log(request)}")

                # If we have not yet reached the strike threshold for banning, challenge the client
                # with a simple human verification flow rather than immediately banning. This avoids
                # penalizing mistaken clients while stopping automated scrapers that don't run JS.
                try:
                    from urllib.parse import quote
                    from django.http import HttpResponseRedirect
                    if strikes < max_strikes:
                        query = request.META.get('QUERY_STRING', '')
                        next_url = path + (('?' + query) if query else '')
                        redirect_to = f"/__human_challenge/?next={quote(next_url)}"
                        return HttpResponseRedirect(redirect_to)
                except Exception:
                    # If redirect fails for any reason, continue with normal rate-limit response
                    logger.exception('Failed to redirect to human challenge page')

                # Record event to audit log for analysis
                try:
                    with open('rate_limit_events.log', 'a') as rf:
                        rf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {ip} | {endpoint_type} | count={rate_data['count']} | strikes={strikes} | limit={limit} | ua={user_agent} | path={log_path}\n")
                except Exception:
                    logger.exception('Failed to write rate_limit_events.log')
                
                # Ban if too many strikes
                if strikes >= max_strikes:
                    ban_until = current_time + ban_duration
                    try:
                        from search.db_utils import safe_cache_set
                        safe_cache_set(ban_key, {
                            'until': ban_until,
                            'reason': f'Exceeded {endpoint_type} rate limit {strikes} times',
                            'endpoint': endpoint_type
                        }, ban_duration)
                    except Exception:
                        try:
                            cache.set(ban_key, {
                                'until': ban_until,
                                'reason': f'Exceeded {endpoint_type} rate limit {strikes} times',
                                'endpoint': endpoint_type
                            }, ban_duration)
                        except Exception:
                            logger.exception('Failed to set ban_key in cache')

                    print(f"[BOT_BANNED] ip={ip} endpoint={endpoint_type} strikes={strikes} ban_duration={ban_duration} ua={user_agent} path={log_path}")
                    
                    # Log to file for monitoring
                    try:
                        with open('blocked_ips.log', 'a') as f:
                            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {ip} | {endpoint_type} | {strikes} strikes | {ban_duration}s | ua={user_agent} | path={log_path}\n")
                    except Exception:
                        logger.exception('Failed to write blocked_ips.log')
                    
                    response = HttpResponse(
                        f'Your IP has been temporarily blocked due to excessive {endpoint_type} requests.\n'
                        f'Ban duration: {ban_duration // 60} minutes.\n'
                        f'Contact the site administrator if you believe this is an error.',
                        status=403,
                        content_type='text/plain'
                    )
                    return response
                
                retry_after = int(rate_data['reset_time'] - current_time)
                response = HttpResponse(
                    f'Rate limit exceeded. Try again in {retry_after} seconds.\n'
                    f'Limit: {limit} requests per {window} seconds for {endpoint_type} endpoints.\n'
                    f'Warning: {strikes}/{max_strikes} strikes. {max_strikes - strikes} more violations will result in a temporary ban.',
                    status=429,
                    content_type='text/plain'
                )
                response['Retry-After'] = str(retry_after)
                response['X-RateLimit-Limit'] = str(limit)
                response['X-RateLimit-Remaining'] = '0'
                response['X-RateLimit-Reset'] = str(int(rate_data['reset_time']))
                return response
            
            counters.set(cache_key, rate_data, window)

        response = self.get_response(request)
        
        # Add rate limit headers to response
        response['X-RateLimit-Limit'] = str(limit)
        response['X-RateLimit-Remaining'] = str(max(0, limit - rate_data['count']))
        response['X-RateLimit-Reset'] = str(int(rate_data['reset_time']))
        
        return response


class AjaxExceptionMiddleware:
    """
    Catch unhandled exceptions and return JSON responses for AJAX or Gemini requests.
    This prevents HTML 500 pages from being returned to fetch() callers that expect JSON.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception as exc:
            # Log full traceback
            logger.exception('Unhandled exception processing request %s', request.path)

            # Determine if client expects JSON: AJAX header, Accept JSON, or gemini route
            accept = (request.META.get('HTTP_ACCEPT') or '')
            is_ajax = request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
            is_json_accept = 'application/json' in accept
            is_gemini_route = request.path.startswith('/translate/gemini/') or request.path.startswith('/gemini/')

            if is_ajax or is_json_accept or is_gemini_route:
                resp = {'error': 'Internal server error'}
                if settings.DEBUG:
                    resp['detail'] = str(exc)
                    resp['traceback'] = traceback.format_exc()
                return JsonResponse(resp, status=500)

            # Not an AJAX/json request — re-raise to let standard handlers take over
            raise


class BotFilterMiddleware:
    """
    Block known bad bots and suspicious user agents.
    
    Blocks:
    - Common scraping bots
    - Headless browsers (when used maliciously)
    - Empty or suspicious user agents
    """
    
    BLOCKED_USER_AGENTS = [
        'python-requests',
        'curl',
        'wget',
        'scrapy',
        'bot',
        'spider',
        'crawler',
        'scraper',
        'http',
        'libwww',
        'snoopy',
        'mechanize',
        'java',
        'headless',
    ]
    
    ALLOWED_BOTS = [
        'googlebot',
        'bingbot',
        'slurp',  # Yahoo
        'duckduckbot',
        'baiduspider',
        'yandexbot',
        'facebookexternalhit',
        'twitterbot',
        'linkedinbot',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        # Skip filtering for authenticated users
        if hasattr(request, 'user') and request.user.is_authenticated:
            return self.get_response(request)
        
        # Skip in DEBUG mode
        if getattr(settings, 'DEBUG', False):
            return self.get_response(request)

        # Skip bot filtering for API endpoints called by server-side proxies
        # (e.g. WordPress wp_remote_get sends a UA containing 'https://' which
        #  matches the broad 'http' blocked pattern)
        skip_paths = ('/update_count/', '/stats/', '/health', '/robots.txt', '/sitemap.xml')
        if request.path in skip_paths or request.path.startswith('/api/'):
            return self.get_response(request)

        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        # Allow empty user agent from browsers (some privacy tools strip UA)
        if not user_agent:
            # But rate limit more aggressively
            pass
        
        # Check if it's an allowed bot
        is_allowed_bot = any(allowed in user_agent for allowed in self.ALLOWED_BOTS)
        if is_allowed_bot:
            return self.get_response(request)
        
        # Block known bad bots
        is_blocked = any(blocked in user_agent for blocked in self.BLOCKED_USER_AGENTS)
        if is_blocked:
            return HttpResponse(
                'Access denied. If you are a legitimate bot, please contact the site administrator.',
                status=403,
                content_type='text/plain'
            )
        
        return self.get_response(request)

import threading
import requests

# Visitor logging is best-effort: under a flood drop rows rather than pile up threads.
_visitor_log_slots = threading.BoundedSemaphore(8)


class VisitorTrackingMiddleware:
    """
    Tracks visitor locations for the heatmap analytics.
    Filters out bots and uses ip-api.com for geolocation.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def get_client_ip(self, request):
        return client_ip(request)

    def __call__(self, request):
        response = self.get_response(request)
        
        # Skip tracking for static files, media, and admin/edit paths
        path = request.path
        if path.startswith('/static/') or path.startswith('/media/') or path.startswith('/edit') or path.startswith('/admin') or path.startswith('/visitor_locations/'):
            return response
            
        ip = self.get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
            
        # Skip tracking in DEBUG mode for local development to avoid spamming the API
        if getattr(settings, 'DEBUG', False) and ip in ('127.0.0.1', 'localhost'):
            # For local testing, we can mock a location or just skip
            # Let's mock a location for local testing so the map works
            threading.Thread(target=self.log_visitor_mock, args=(ip, user_agent, path)).start()
            return response
            
        # Basic bot detection — keyword check
        bot_keywords = ['bot', 'spider', 'crawler', 'scraper', 'google', 'bing', 'yandex', 'baidu', 'curl', 'wget', 'python-requests']
        is_bot = any(keyword in user_agent.lower() for keyword in bot_keywords)

        if not is_bot:
            # Heuristic: old Chrome versions (< 100) are almost always headless bots or
            # scrapers in 2026 — Chrome 100 shipped April 2022, anything older is suspicious.
            chrome_match = re.search(r'Chrome/(\d+)\.', user_agent)
            if chrome_match and int(chrome_match.group(1)) < 100:
                is_bot = True

        if not is_bot:
            # Heuristic: Windows NT 5.x / 6.0 / 6.1 (XP / Vista / Win 7) are all
            # end-of-life and overwhelmingly used as fake UA strings by bot networks.
            if re.search(r'Windows NT [56]\.[01]', user_agent):
                is_bot = True

        if not is_bot and not user_agent:
            is_bot = True  # Empty UA = bot

        if is_bot:
            return response  # Don't log bots to save DB space and API calls
            
        # Run geolocation and logging in a background thread to avoid blocking the response
        if _visitor_log_slots.acquire(blocking=False):
            threading.Thread(target=self.log_visitor_in_slot, args=(ip, user_agent, path), daemon=True).start()

        return response

    def log_visitor_in_slot(self, ip, user_agent, path):
        from django.db import connections

        try:
            self.log_visitor(ip, user_agent, path)
        finally:
            connections.close_all()  # This thread's connection is not closed for us
            _visitor_log_slots.release()
        
    def log_visitor_mock(self, ip, user_agent, path):
        """Mock visitor logging for local development."""
        from search.models import VisitorLocation
        import random
        
        try:
            VisitorLocation.objects.create(
                ip_address=None,
                user_agent=user_agent,
                path=path,
                country='Localhost',
                city='Local City',
                # Random coordinates for testing the heatmap
                latitude=random.uniform(-90, 90),
                longitude=random.uniform(-180, 180),
                is_bot=False
            )
        except Exception as e:
            logger.error(f"Error saving mock visitor log: {e}")
            
    def log_visitor(self, ip, user_agent, path):
        from search.models import VisitorLocation
        from django.core.cache import cache
        
        # Check if we already have this IP's location cached
        cache_key = f'geoip_{ip}'
        geo_data = cache.get(cache_key)
        
        if not geo_data:
            try:
                # Use ip-api.com (free, no key required, 45 requests/minute limit)
                res = requests.get(f'http://ip-api.com/json/{ip}?fields=status,country,city,lat,lon,proxy,hosting', timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if data.get('status') == 'success':
                        is_bot_network = data.get('proxy', False) or data.get('hosting', False)
                        # Filter out extreme bot traffic from typical scraping countries if they are abnormally high
                        if data.get('country') in ['Vietnam', 'China', 'Singapore', 'Bangladesh', 'Hong Kong', 'Russia']:
                            is_bot_network = True
                        geo_data = {
                            'country': data.get('country'),
                            'city': data.get('city'),
                            'latitude': data.get('lat'),
                            'longitude': data.get('lon'),
                            'is_bot': is_bot_network
                        }
                        # Cache for 24 hours (including bot-network flag so we skip them on repeat visits)
                        cache.set(cache_key, geo_data, 60 * 60 * 24)
            except Exception as e:
                logger.error(f"Error fetching geoip for {ip}: {e}")
                
        if geo_data:
            # Skip storing records for known proxy/hosting IPs — they're bots and waste DB space.
            if geo_data.get('is_bot', False):
                return
            try:
                VisitorLocation.objects.create(
                    ip_address=None,  # Privacy: don't store raw IP
                    user_agent=user_agent,
                    path=path,
                    country=geo_data.get('country'),
                    city=geo_data.get('city'),
                    latitude=geo_data.get('latitude'),
                    longitude=geo_data.get('longitude'),
                    is_bot=False
                )
            except Exception as e:
                logger.error(f"Error saving visitor log: {e}")
