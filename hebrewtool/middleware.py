"""
Rate limiting and bot protection middleware.

Prevents bot flooding by implementing IP-based rate limiting
and User-Agent filtering for suspicious crawlers.
"""

import time
from django.http import HttpResponse
from django.core.cache import cache
from django.conf import settings


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
        
        # Determine rate limit based on endpoint
        if 'verse' in request.GET and 'chapter' in request.GET:
            # Individual verse lookup - most expensive
            limit = 60
            window = 60  # seconds
            endpoint_type = 'verse'
        elif 'chapter' in request.GET and 'book' in request.GET:
            # Chapter view
            limit = 120
            window = 60
            endpoint_type = 'chapter'
        elif path.startswith('/translate/') or path.startswith('/api/'):
            # Translation API
            limit = 30
            window = 60
            endpoint_type = 'api'
        else:
            # General pages
            limit = 180
            window = 60
            endpoint_type = 'general'
        
        cache_key = f'ratelimit:{endpoint_type}:{ip}'
        
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
                retry_after = int(rate_data['reset_time'] - current_time)
                response = HttpResponse(
                    f'Rate limit exceeded. Try again in {retry_after} seconds.\n'
                    f'Limit: {limit} requests per {window} seconds for {endpoint_type} endpoints.',
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
