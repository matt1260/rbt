"""
Rate limiting and bot protection middleware.

Prevents bot flooding by implementing IP-based rate limiting
and User-Agent filtering for suspicious crawlers.
"""

import time
import logging
from django.http import HttpResponse
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)


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
        """Extract client IP from request headers."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def __call__(self, request):
        # Skip rate limiting for authenticated users (editors)
        if hasattr(request, 'user') and request.user.is_authenticated:
            return self.get_response(request)
        
        # Skip rate limiting in DEBUG mode for local development
        if getattr(settings, 'DEBUG', False):
            return self.get_response(request)
        
        ip = self.get_client_ip(request)
        path = request.path
        
        # Check if IP is banned
        ban_key = f'banned:{ip}'
        ban_data = cache.get(ban_key)
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
        if 'verse' in request.GET and 'chapter' in request.GET:
            # Individual verse lookup - VERY AGGRESSIVE (bots abuse this)
            limit = 10  # Only 10 verse requests per minute
            window = 60
            endpoint_type = 'verse'
            max_strikes = 2  # Ban after 2 violations
            ban_duration = 3600  # 1 hour ban
        elif 'chapter' in request.GET and 'book' in request.GET:
            # Chapter view
            limit = 30
            window = 60
            endpoint_type = 'chapter'
            max_strikes = 3
            ban_duration = 1800  # 30 min ban
        elif path.startswith('/translate/') or path.startswith('/api/'):
            # Translation API
            limit = 10
            window = 60
            endpoint_type = 'api'
            max_strikes = 2
            ban_duration = 3600
        else:
            # General pages
            limit = 60
            window = 60
            endpoint_type = 'general'
            max_strikes = 5
            ban_duration = 600  # 10 min ban
        
        cache_key = f'ratelimit:{endpoint_type}:{ip}'
        strikes_key = f'strikes:{endpoint_type}:{ip}'
        
        # Get current request count and timestamp
        rate_data = cache.get(cache_key, {'count': 0, 'reset_time': time.time() + window})
        
        current_time = time.time()
        
        # Reset counter if window has passed
        if current_time >= rate_data['reset_time']:
            rate_data = {'count': 1, 'reset_time': current_time + window}
            cache.set(cache_key, rate_data, window)
        else:
            # Increment counter
            rate_data['count'] += 1
            
            # Check if limit exceeded
            if rate_data['count'] > limit:
                # Add a strike
                strikes = cache.get(strikes_key, 0) + 1
                cache.set(strikes_key, strikes, 7200)  # Strikes expire after 2 hours
                
                user_agent = request.META.get('HTTP_USER_AGENT', '')[:200]
                logger.warning(f"[RATE LIMIT] IP {ip} exceeded {endpoint_type} limit (strike {strikes}/{max_strikes}) UA={user_agent}")
                # Also print to stdout so platform logs capture the IP immediately
                print(f"[RATE_LIMIT] ip={ip} endpoint={endpoint_type} count={rate_data['count']} strikes={strikes} ua={user_agent} path={path}")

                # Record event to audit log for analysis
                try:
                    with open('rate_limit_events.log', 'a') as rf:
                        rf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {ip} | {endpoint_type} | count={rate_data['count']} | strikes={strikes} | limit={limit} | ua={user_agent} | path={path}\n")
                except Exception:
                    logger.exception('Failed to write rate_limit_events.log')
                
                # Ban if too many strikes
                if strikes >= max_strikes:
                    ban_until = current_time + ban_duration
                    cache.set(ban_key, {
                        'until': ban_until,
                        'reason': f'Exceeded {endpoint_type} rate limit {strikes} times',
                        'endpoint': endpoint_type
                    }, ban_duration)
                    logger.error(f"[BOT BANNED] IP {ip} banned for {ban_duration}s (reason: {strikes} {endpoint_type} violations) UA={user_agent}")
                    # Print to stdout for immediate log visibility
                    print(f"[BOT_BANNED] ip={ip} endpoint={endpoint_type} strikes={strikes} ban_duration={ban_duration} ua={user_agent} path={path}")
                    
                    # Log to file for monitoring
                    try:
                        with open('blocked_ips.log', 'a') as f:
                            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {ip} | {endpoint_type} | {strikes} strikes | {ban_duration}s | ua={user_agent} | path={path}\n")
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
            
            cache.set(cache_key, rate_data, window)
        
        response = self.get_response(request)
        
        # Add rate limit headers to response
        response['X-RateLimit-Limit'] = str(limit)
        response['X-RateLimit-Remaining'] = str(max(0, limit - rate_data['count']))
        response['X-RateLimit-Reset'] = str(int(rate_data['reset_time']))
        
        return response


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
