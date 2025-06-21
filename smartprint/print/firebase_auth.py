
import json
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.conf import settings
from firebase_admin import auth as firebase_auth

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
        
        # Verify the Firebase ID token using Admin SDK
        try:
            decoded_token = firebase_auth.verify_id_token(id_token)
            firebase_uid = decoded_token['uid']
            email = decoded_token.get('email', '')
            name = decoded_token.get('name', '')
            phone = decoded_token.get('phone_number', '')
            
            print(f"✅ Token verified successfully for user: {firebase_uid}")
            print(f"   Email: {email}")
            print(f"   Name: {name}")
            print(f"   Phone: {phone}")
            
        except Exception as e:
            print(f"❌ Token verification failed: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Invalid token'}, status=401)
        
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
            print(f"✅ User {'created' if created else 'found'}: {user.username}")
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
            print(f"✅ Phone user {'created' if created else 'found'}: {user.username}")
        else:
            print(f"❌ Unable to create user - missing required fields")
            return JsonResponse({'success': False, 'error': 'Unable to create user account'}, status=400)
        
        # Login the user
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)
        
        # Store user info in session
        request.session['firebase_uid'] = firebase_uid
        request.session['auth_method'] = auth_method
        
        print(f"✅ User logged in successfully: {user.username}")
        
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
        print("❌ Invalid JSON in request")
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        print(f"❌ Firebase auth error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Authentication failed'}, status=500)


def verify_firebase_token(id_token):
    """
    Verify Firebase ID token using Firebase Admin SDK
    This function is now deprecated in favor of direct Admin SDK usage above
    """
    try:
        # Use Firebase Admin SDK to verify token
        decoded_token = firebase_auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        print(f"Token verification error: {str(e)}")
        return None
