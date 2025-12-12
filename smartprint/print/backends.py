"""
Custom authentication backend for D1 database admin users
"""
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password
from django.conf import settings
import requests
import json


class D1AdminUserBackend(BaseBackend):
    """
    Custom authentication backend that authenticates against D1 database admin_users table
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user against D1 database admin_users table
        """
        if username is None or password is None:
            return None
        
        try:
            # Get admin user from D1 database
            api_url = getattr(settings, 'WORKER_API_URL', '').strip()
            api_key = getattr(settings, 'WORKER_API_KEY', '')
            
            if not api_url or not api_key:
                return None
            
            # Build endpoint
            base_url = api_url.rstrip('/')
            if '/add-contact' in base_url:
                endpoint = base_url.replace('/add-contact', '/get-admin-user')
            elif '/add-vendor-register' in base_url:
                endpoint = base_url.replace('/add-vendor-register', '/get-admin-user')
            else:
                endpoint = base_url + '/get-admin-user'
            
            # Fetch user from D1
            response = requests.post(
                endpoint,
                json={'username': username},
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': api_key
                },
                timeout=10
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            if not data.get('success'):
                return None
            
            user_data = data.get('user')
            if not user_data:
                return None
            
            # Check password
            stored_hash = user_data.get('password_hash')
            if not stored_hash:
                return None
            
            # Verify password using Django's password checker
            if not check_password(password, stored_hash):
                return None
            
            # Get or create Django User object (for session management only)
            # All authentication is done via D1, Django User is just for session compatibility
            try:
                user = User.objects.get(username=username)
                # Update user attributes from D1
                user.email = user_data.get('email', '')
                user.first_name = user_data.get('first_name', '')
                user.last_name = user_data.get('last_name', '')
                user.is_superuser = user_data.get('is_superuser', False)
                user.is_staff = user_data.get('is_staff', True)
                user.is_active = user_data.get('is_active', True)
                # Store D1 password hash in Django (for compatibility, but auth is via D1)
                if stored_hash != user.password:
                    user.password = stored_hash
                user.save()
            except User.DoesNotExist:
                # Create new Django User object (for session compatibility only)
                # We store the D1 password hash directly (Django format compatible)
                user = User(
                    username=username,
                    email=user_data.get('email', ''),
                    first_name=user_data.get('first_name', ''),
                    last_name=user_data.get('last_name', ''),
                    is_superuser=user_data.get('is_superuser', False),
                    is_staff=user_data.get('is_staff', True),
                    is_active=user_data.get('is_active', True),
                    password=stored_hash  # Store D1 hash directly (already in Django format)
                )
                user.save()
            
            # Store D1 user data in user object for access control
            user.d1_user_id = user_data.get('id')
            user.d1_permissions = user_data.get('permissions')
            
            return user
            
        except Exception as e:
            # Log error but don't expose it
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in D1AdminUserBackend.authenticate: {e}")
            return None
    
    def get_user(self, user_id):
        """
        Get user by ID (for session management)
        """
        try:
            user = User.objects.get(pk=user_id)
            # Verify user still exists in D1 and is active
            if not user.is_active:
                return None
            
            # Optionally refresh from D1 to ensure permissions are up to date
            # This is optional and can be done on-demand
            return user
        except User.DoesNotExist:
            return None

