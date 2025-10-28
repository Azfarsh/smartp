"""
Custom middleware for session management and authentication
"""
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth import logout
import logging

logger = logging.getLogger(__name__)

class SessionValidationMiddleware:
    """
    Middleware to validate user sessions and handle authentication
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # URLs that don't require authentication
        self.exempt_urls = [
            '/',
            '/login/',
            '/auth-receiver/',  # Fixed: was /auth_receiver/
            '/vendor-login/',
            '/vendor-register/',
            '/vendor-pricing/',
            '/vendor-about/',
            '/photoprint/',
            '/drive/oauth/start/',
            '/drive/oauth/callback/',
            '/drive/list/',
            '/drive/download/',
            '/create_razorpay_order/',
            '/verify_razorpay_payment/',
            '/forgot-password/',
            '/verify-reset-code/',
            '/reset-password/',
            '/vendor-about/',
            '/static/',
            '/media/',
        ]
    
    def __call__(self, request):
        # Skip session validation for exempt URLs
        if any(request.path.startswith(url) for url in self.exempt_urls):
            response = self.get_response(request)
            return response
        
        # Check if user is authenticated
        if not request.user.is_authenticated:
            # For AJAX requests, return 401
            if request.headers.get('Content-Type') == 'application/json' or \
               request.headers.get('Accept') == 'application/json':
                from django.http import JsonResponse
                return JsonResponse({'error': 'Authentication required'}, status=401)
            
            # For regular requests, redirect to login
            return redirect('/login/')
        
        # Check if session is valid
        if not request.session.get('_auth_user_id'):
            logger.warning(f"Invalid session for user {request.user.email}")
            logout(request)
            return redirect('/login/')
        
        response = self.get_response(request)
        return response
