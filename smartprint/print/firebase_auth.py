
import json
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.conf import settings

@csrf_exempt
def firebase_auth(request):
    """
    Handle Firebase authentication (Google and Phone)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)
    
    try:
        data = json.loads(request.body)
        id_token = data.get('id_token')
        auth_method = data.get('auth_method', 'google')
        
        if not id_token:
            return JsonResponse({'success': False, 'error': 'ID token required'}, status=400)
        
        # Verify the Firebase ID token
        user_info = verify_firebase_token(id_token)
        
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Invalid token'}, status=401)
        
        # Extract user information
        firebase_uid = user_info.get('uid')
        email = user_info.get('email', '')
        name = user_info.get('name', '')
        phone = user_info.get('phone_number', '')
        
        # Create or get Django user
        if auth_method == 'google' and email:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': email,
                    'first_name': name.split(' ')[0] if name else '',
                    'last_name': ' '.join(name.split(' ')[1:]) if name and ' ' in name else '',
                }
            )
        elif auth_method == 'phone' and phone:
            # For phone auth, use firebase_uid as username
            username = f"phone_{firebase_uid}"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': name.split(' ')[0] if name else 'User',
                    'last_name': ' '.join(name.split(' ')[1:]) if name and ' ' in name else '',
                }
            )
        else:
            return JsonResponse({'success': False, 'error': 'Unable to create user account'}, status=400)
        
        # Store Firebase UID in user profile (you might want to create a UserProfile model)
        # For now, we'll store it in the user's last_login field as a simple solution
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)
        
        # Store user info in session
        request.session['firebase_uid'] = firebase_uid
        request.session['auth_method'] = auth_method
        
        return JsonResponse({
            'success': True,
            'message': 'Authentication successful',
            'redirect_url': '/userdashboard/',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'name': f"{user.first_name} {user.last_name}".strip(),
                'auth_method': auth_method
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        print(f"Firebase auth error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Authentication failed'}, status=500)


def verify_firebase_token(id_token):
    """
    Verify Firebase ID token using Google's public keys
    """
    try:
        # Use Firebase Admin SDK or verify manually
        # For simplicity, we'll use Google's token verification endpoint
        verification_url = f"https://www.googleapis.com/oauth2/v3/tokeninfo?id_token={id_token}"
        
        response = requests.get(verification_url, timeout=10)
        
        if response.status_code == 200:
            token_info = response.json()
            
            # Verify the token is for your Firebase project
            expected_audience = "1:48548800228:web:a2b523c97d5824f1836ef1"  # Your Firebase app ID
            
            if token_info.get('aud') == expected_audience:
                return token_info
            else:
                print(f"Token audience mismatch: {token_info.get('aud')} != {expected_audience}")
                return None
        else:
            print(f"Token verification failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"Token verification error: {str(e)}")
        return None
