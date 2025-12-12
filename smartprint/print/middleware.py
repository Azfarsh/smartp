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
            '/admin/',  # Django admin URLs (handled by Django's admin authentication)
            # Note: /admin-dashboard/ is NOT exempt - it uses @staff_member_required decorator
        ]
    
    def __call__(self, request):
        # Skip session validation for exempt URLs
        if any(request.path.startswith(url) for url in self.exempt_urls):
            response = self.get_response(request)
            return response
        
        # Special handling for admin-dashboard: enforce strict authentication
        # Similar to vendor dashboard - check session explicitly
        if request.path.startswith('/admin-dashboard/'):
            from django.contrib.auth.models import AnonymousUser
            from django.contrib.auth import logout as django_logout
            
            # Get session user ID
            session_user_id = request.session.get('_auth_user_id')
            
            # Check if user is authenticated (both session and user object must be valid)
            is_authenticated = getattr(request.user, 'is_authenticated', False)
            is_staff = getattr(request.user, 'is_staff', False)
            
            # If no session user ID OR user is not authenticated, force logout and redirect
            if not session_user_id or not is_authenticated:
                # Clear any cached authentication
                if is_authenticated:
                    django_logout(request)
                # Ensure user is AnonymousUser
                request.user = AnonymousUser()
                # Redirect to admin login
                login_url = reverse('admin:login') + '?next=' + request.get_full_path()
                return redirect(login_url)
            
            # If authenticated but not staff, also redirect to admin login
            if not is_staff:
                login_url = reverse('admin:login') + '?next=' + request.get_full_path()
                return redirect(login_url)
            
            # User is authenticated and staff - proceed to view
            # Add cache-control headers to prevent browser caching
            response = self.get_response(request)
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
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
