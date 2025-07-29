from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
import boto3
import datetime
import json
import requests
import uuid
import random
import re
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
import os
import base64
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import traceback
from PIL import Image, ImageDraw
import io
# ─────────────────────────────────────────────────────────────
# BASIC PAGE VIEWS
# ─────────────────────────────────────────────────────────────


def home(request):
    return render(request, 'home.html')


def get_vendor_details_by_email(email):
    s3 = boto3.client('s3',
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_KEY,
        endpoint_url=settings.R2_ENDPOINT,
        region_name='auto'
    )
    try:
        reg_key = f'vendor_register_details/{sanitize_email(email)}/registration_details.json'
        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
        vendor_data = json.loads(response['Body'].read().decode('utf-8'))
        return {
            'vendor_id': vendor_data.get('vendor_id', ''),
            'vendor_name': vendor_data.get('vendor_name', ''),
            'vendor_email': vendor_data.get('vendor_email', ''),
            'phone_number': vendor_data.get('phone_number', ''),
            'shop_address': vendor_data.get('shop_address', ''),
            'city': vendor_data.get('city', ''),
        }
    except Exception as e:
        print(f"Error fetching vendor details for {email}: {str(e)}")
        return None


def get_vendor_specific_jobs(vendor_id):
    """
    Fetch jobs specifically for a given vendor from their folder in R2
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=settings.R2_ACCESS_KEY,
                      aws_secret_access_key=settings.R2_SECRET_KEY,
                      endpoint_url=settings.R2_ENDPOINT,
                      region_name='auto')

    try:
        file_data = []
        # Get files from vendor's specific folders
        vendor_print_prefix = f'vendor_print_jobs/{vendor_id}/'
        vendor_manual_prefix = f'vendor_manual_print_jobs/{vendor_id}/'
        
        vendor_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=vendor_print_prefix)
        manual_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=vendor_manual_prefix)

        # Combine both object lists
        all_objects = []
        if vendor_objects.get("Contents"):
            all_objects.extend(vendor_objects.get("Contents", []))
        if manual_objects.get("Contents"):
            all_objects.extend(manual_objects.get("Contents", []))

        print(f"🔍 Searching for jobs for vendor {vendor_id}")
        print(f"📁 Vendor print jobs prefix: {vendor_print_prefix}")
        print(f"📁 Vendor manual print jobs prefix: {vendor_manual_prefix}")

        for obj in all_objects:
            key = obj["Key"]
            filename = key.split("/")[-1]
            # Skip .json files (metadata, not print jobs) and folders
            if filename.lower().endswith('.json') or not filename:
                continue
                
            try:
                # Get object metadata first
                head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                metadata = head_response.get('Metadata', {})
                job_completed = metadata.get('job_completed', 'NO').upper()
                
                # Only include jobs with job_completed == 'NO' or 'YES'
                if job_completed not in ['NO', 'YES']:
                    continue
                    
                # Generate presigned URL for preview
                url = s3.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={
                        'Bucket': settings.R2_BUCKET,
                        'Key': key
                    },
                    ExpiresIn=3600
                )
                
                # Generate download URL for direct file access
                download_url = s3.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={
                        'Bucket': settings.R2_BUCKET,
                        'Key': key,
                        'ResponseContentDisposition': f'inline; filename="{filename}"'
                    },
                    ExpiresIn=3600
                )
                
                # Determine file type and icon
                file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
                file_type = get_file_type(file_extension)
                
                # Calculate estimated pages if not in metadata
                pages = metadata.get('pages', estimate_pages_from_size(obj.get('Size', 0), file_extension))
                
                # Build file info
                file_info = {
                    "filename": filename,
                    "job_id": metadata.get('job_id', ''),
                    "preview_url": url,
                    "download_url": download_url,
                    "file_type": file_type,
                    "file_extension": file_extension,
                    "size": format_file_size(obj.get('Size', 0)),
                    "user": metadata.get('user', 'Auto User'),
                    "pages": pages,
                    "status": metadata.get('status', 'pending').title(),
                    "uploaded_at": obj["LastModified"].strftime("%Y-%m-%d %H:%M"),
                    "priority": metadata.get('priority', 'Medium'),
                    "copies": metadata.get('copies', '1'),
                    "color": metadata.get('color', 'Black and White'),
                    "orientation": metadata.get('orientation', 'portrait'),
                    "pageRange": metadata.get('pagerange', 'all'),
                    "specificPages": metadata.get('specificpages', ''),
                    "pageSize": metadata.get('pagesize', 'A4'),
                    "spiralBinding": metadata.get('spiralbinding', 'No'),
                    "lamination": metadata.get('lamination', 'No'),
                    "job_completed": metadata.get('job_completed', 'NO'),
                    "trash": metadata.get('trash', 'NO'),
                    "timestamp": metadata.get('timestamp', obj["LastModified"].isoformat()),
                    "service_type": metadata.get('service_type', ''),
                    "service_name": metadata.get('service_name', ''),
                    "token": metadata.get('token', ''),
                    "vendor_id": vendor_id,
                    "feedback": metadata.get('feedback', ''),
                    "quality": metadata.get('quality', ''),
                    "thickness": metadata.get('thickness', '')
                }
                
                # Create print options string
                file_info["print_options"] = f"{file_info['copies']} copies, {file_info['color']}, {file_info['orientation']}"
                file_data.append(file_info)
                print(f"✅ Found job for vendor {vendor_id}: {filename} (status: {metadata.get('status', 'pending')}, completed: {job_completed})")
                
            except Exception as e:
                print(f"Error processing vendor file {key}: {str(e)}")
                continue
                
        # Count jobs by status
        pending_count = len([job for job in file_data if job['job_completed'] == 'NO'])
        completed_count = len([job for job in file_data if job['job_completed'] == 'YES'])
        print(f"📋 Total jobs found for vendor {vendor_id}: {len(file_data)} (Pending: {pending_count}, Completed: {completed_count})")
        return file_data
        
    except Exception as e:
        print(f"Error listing vendor-specific R2 files: {str(e)}")
        return []

def vendordashboard(request):
    try:
        # Get vendor details from session
        vendor_details = None
        vendor_email = request.session.get('vendor_email')
        vendor_id = request.session.get('vendor_id')  # Get vendor_id directly from session
        
        print(f"🔍 Session data - Email: {vendor_email}, Vendor ID: {vendor_id}")
        
        if vendor_email and vendor_id:
            vendor_details = get_vendor_details_by_email(vendor_email)
            if vendor_details:
                # Ensure vendor_id matches
                if vendor_details.get('vendor_id') != vendor_id:
                    vendor_id = vendor_details.get('vendor_id')
                    request.session['vendor_id'] = vendor_id  # Update session with correct vendor_id
                print(f"🔍 Loading dashboard for vendor: {vendor_details.get('vendor_name')} (ID: {vendor_id})")
            else:
                print("❌ Could not fetch vendor details from R2")
        elif vendor_email and not vendor_id:
            # Try to get vendor_id from vendor details
            vendor_details = get_vendor_details_by_email(vendor_email)
            if vendor_details:
                vendor_id = vendor_details.get('vendor_id')
                request.session['vendor_id'] = vendor_id
                print(f"🔍 Retrieved vendor ID from details: {vendor_id}")
        
        if not vendor_id:
            print("❌ No vendor ID found in session or vendor details")
            return render(request, 'vendordashboard.html', {
                'manual_print_jobs': [],
                'print_requests': [],
                'completed_jobs': [],
                'vendor_details': vendor_details,
                'vendor_details_error': 'Vendor not authenticated. Please login again.',
                'total_jobs': 0,
                'manual_print_count': 0,
                'print_requests_count': 0,
                'completed_jobs_count': 0,
            })

        # Fetch vendor-specific jobs
        files = get_vendor_specific_jobs(vendor_id)
        
        manual_services = [
            'photo_print', 'digital_print', 'project_binding', 'gloss_printing', 'jumbo_printing'
        ]
        manual_print_jobs = []
        print_requests = []
        completed_jobs = []
        
        for job in files:
            job_completed = job.get('job_completed', 'NO').upper()
            service_type = job.get('service_type', '').strip().lower()
            
            if job_completed == 'NO':
                if service_type in manual_services:
                    manual_print_jobs.append(job)
                else:
                    # Regular print jobs, passport prints, photo prints, etc.
                    print_requests.append(job)
            elif job_completed == 'YES':
                completed_jobs.append(job)

        context = {
            'manual_print_jobs': manual_print_jobs,
            'print_requests': print_requests,
            'completed_jobs': completed_jobs,
            'vendor_details': vendor_details,
            'total_jobs': len(manual_print_jobs) + len(print_requests) + len(completed_jobs),
            'manual_print_count': len(manual_print_jobs),
            'print_requests_count': len(print_requests),
            'completed_jobs_count': len(completed_jobs),
        }
        return render(request, 'vendordashboard.html', context)
        
    except Exception as e:
        print(f"Error loading vendor dashboard data: {str(e)}")
        return render(request, 'vendordashboard.html', {
            'manual_print_jobs': [],
            'print_requests': [],
            'completed_jobs': [],
            'vendor_details': None,
            'vendor_details_error': 'Dashboard error. Please try again later.',
            'total_jobs': 0,
            'manual_print_count': 0,
            'print_requests_count': 0,
            'completed_jobs_count': 0,
        })



def get_user_details_from_r2(user_email):
    """
    Fetch user details from R2 storage signup folder
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=settings.R2_ACCESS_KEY,
                      aws_secret_access_key=settings.R2_SECRET_KEY,
                      endpoint_url=settings.R2_ENDPOINT,
                      region_name='auto')

    try:
        # List all files in signupdetails folder
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='signupdetails/')

        for obj in objects.get("Contents", []):
            key = obj["Key"]
            if key.endswith('.json'):
                try:
                    # Get the JSON file content
                    response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                    content = response['Body'].read().decode('utf-8')
                    user_data = json.loads(content)

                    # Check if this is the user we're looking for
                    if user_data.get('email') == user_email:
                        return {
                            'name': user_data.get('name', ''),
                            'email': user_data.get('email', ''),
                            'profile_picture': user_data.get('picture', ''),
                            'given_name': user_data.get('given_name', ''),
                            'family_name': user_data.get('family_name', ''),
                            'locale': user_data.get('locale', ''),
                            'email_verified': user_data.get('email_verified', False)
                        }
                except Exception as e:
                    print(f"Error reading user data from {key}: {str(e)}")
                    continue

        return None

    except Exception as e:
        print(f"Error fetching user details from R2: {str(e)}")
        return None


def get_user_jobs_from_r2(user_email):
    """
    Get all jobs uploaded by a specific user from R2 storage
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=settings.R2_ACCESS_KEY,
                      aws_secret_access_key=settings.R2_SECRET_KEY,
                      endpoint_url=settings.R2_ENDPOINT,
                      region_name='auto')

    try:
        # List all files in the user's folder
        user_prefix = f"users/{user_email}/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=user_prefix)
        user_jobs = []

        for obj in objects.get("Contents", []):
            key = obj["Key"]
            filename = key.split("/")[-1]

            # Skip if it's just the folder itself
            if filename == "":
                continue

            try:
                # Generate presigned URL for preview
                url = s3.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={
                        'Bucket': settings.R2_BUCKET,
                        'Key': key
                    },
                    ExpiresIn=3600
                )

                # Get object metadata
                head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                metadata = head_response.get('Metadata', {})

                # Determine file type and icon
                file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
                file_type = get_file_type(file_extension)

                # Calculate estimated pages if not in metadata
                pages = metadata.get('pages', estimate_pages_from_size(obj.get('Size', 0), file_extension))

                # Build job info
                job_info = {
                    "filename": filename,
                    "preview_url": url,
                    "file_type": file_type,
                    "file_extension": file_extension,
                    "size": format_file_size(obj.get('Size', 0)),
                    "pages": pages,
                    "status": metadata.get('status', 'pending').title(),
                    "uploaded_at": obj["LastModified"].strftime("%Y-%m-%d %H:%M"),
                    "priority": metadata.get('priority', 'Medium'),
                    "copies": metadata.get('copies', '1'),
                    "color": metadata.get('color', 'Black and White'),
                    "orientation": metadata.get('orientation', 'portrait'),
                    "pageRange": metadata.get('pagerange', 'all'),
                    "specificPages": metadata.get('specificpages', ''),
                    "pageSize": metadata.get('pagesize', 'A4'),
                    "spiralBinding": metadata.get('spiralbinding', 'No'),
                    "lamination": metadata.get('lamination', 'No'),
                    "job_completed": metadata.get('job_completed', 'NO'),
                    "timestamp": metadata.get('timestamp', obj["LastModified"].isoformat()),
                    "vendor": metadata.get('vendor', 'firozshop'),
                    "service_type": metadata.get('service_type', ''),
                    "job_id": metadata.get('job_id', ''),
                    "token": metadata.get('token', ''),
                    "feedback": metadata.get('feedback', ''),
                    "quality": metadata.get('quality', ''),
                    "thickness": metadata.get('thickness', ''),
                    "service_name": metadata.get('service_name', '')
                }

                # Fetch vendor coordinates if vendor is assigned
                vendor_id = job_info.get('vendor')
                if vendor_id and vendor_id != 'firozshop':
                    try:
                        # Get vendor email from vendor ID
                        vendor_email = get_vendor_email_by_vendor_id(vendor_id)
                        print(f"Vendor ID {vendor_id} maps to email: {vendor_email}")
                        
                        if vendor_email and vendor_email != 'firozshop@example.com':
                            reg_key = f'vendor_register_details/{sanitize_email(vendor_email)}/registration_details.json'
                            vendor_response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
                            vendor_data = json.loads(vendor_response['Body'].read().decode('utf-8'))
                            job_info['vendor_lat'] = vendor_data.get('latitude', '')
                            job_info['vendor_lng'] = vendor_data.get('longitude', '')
                            print(f"Found coordinates for vendor {vendor_id}: lat={job_info['vendor_lat']}, lng={job_info['vendor_lng']}")
                        else:
                            print(f"No vendor email found for vendor ID: {vendor_id}")
                            job_info['vendor_lat'] = ''
                            job_info['vendor_lng'] = ''
                    except Exception as e:
                        print(f"Error fetching vendor coordinates for vendor ID {vendor_id}: {str(e)}")
                        job_info['vendor_lat'] = ''
                        job_info['vendor_lng'] = ''
                else:
                    job_info['vendor_lat'] = ''
                    job_info['vendor_lng'] = ''

                # Create print options string
                job_info["print_options"] = f"{job_info['copies']} copies, {job_info['color']}, {job_info['orientation']}"

                user_jobs.append(job_info)

            except Exception as e:
                print(f"Error processing user file {key}: {str(e)}")
                continue

        # Sort by upload date (most recent first)
        user_jobs.sort(key=lambda x: x['timestamp'], reverse=True)
        return user_jobs

    except Exception as e:
        print(f"Error getting user jobs from R2: {str(e)}")
        return []


def userdashboard(request):
    # Check if user is authenticated
    if not request.user.is_authenticated:
        return redirect('/login/')

    # Fetch user details from R2 storage
    user_details = get_user_details_from_r2(request.user.email)

    # Get user's recent jobs
    user_jobs = get_user_jobs_from_r2(request.user.email)

    # Calculate statistics
    total_jobs = len(user_jobs)
    pending_jobs = len([job for job in user_jobs if job['job_completed'] == 'NO'])
    completed_jobs = len([job for job in user_jobs if job['job_completed'] == 'YES'])

    # Calculate total earnings this month (example calculation)
    current_month_jobs = [job for job in user_jobs if job['uploaded_at'].startswith(datetime.datetime.now().strftime("%Y-%m"))]
    total_earnings = len(current_month_jobs) * 50  # Example: ₹50 per job

    context = {
        'user': request.user,
        'user_details': user_details,
        'firebase_uid': request.session.get('firebase_uid'),
        'auth_method': request.session.get('auth_method', 'unknown'),
        'user_jobs': user_jobs,  # Show all jobs
        'user_jobs_json': json.dumps(user_jobs),  # JSON serialized for JavaScript
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'completed_jobs': completed_jobs,
        'total_earnings': total_earnings
    }
    return render(request, 'userdashboard.html', context)


# ─────────────────────────────────────────────────────────────
# FILE LISTING FROM R2
# ─────────────────────────────────────────────────────────────

def get_print_requests(request):
    try:
        # Get vendor details from session to filter jobs
        vendor_email = request.session.get('vendor_email')
        vendor_id = request.session.get('vendor_id')  # Get vendor_id directly from session
        
        print(f"🔍 get_print_requests - Session data - Email: {vendor_email}, Vendor ID: {vendor_id}")
        
        if not vendor_id and vendor_email:
            # Try to get vendor_id from vendor details
            vendor_details = get_vendor_details_by_email(vendor_email)
            if vendor_details:
                vendor_id = vendor_details.get('vendor_id')
                request.session['vendor_id'] = vendor_id
                print(f"🔍 Retrieved vendor ID from details: {vendor_id}")
        
        if not vendor_id:
            print("❌ No vendor ID found in session - returning empty job list")
            return JsonResponse({"print_requests": []}, status=200)
        
        # Get vendor-specific jobs instead of all jobs
        files = get_vendor_specific_jobs(vendor_id)
        return JsonResponse({"print_requests": files}, status=200)
    except Exception as e:
        print(f"Error in get_print_requests: {str(e)}")
        return JsonResponse({"error": str(e), "print_requests": []}, status=500)

# ─────────────────────────────────────────────────────────────
# AUTO PRINT ENDPOINT FOR WEBSOCKET INTEGRATION
# ─────────────────────────────────────────────────────────────


@csrf_exempt
def auto_print_documents(request):
    """
    Get pending print jobs and send them to connected vendor clients via WebSocket
    (Now only for admin or dashboard, not for vendor client polling)
    """
    if request.method == 'POST':
        try:
            # Get all files with job_completed = 'NO' (from vendor folders only)
            pending_jobs = get_pending_print_jobs()

            if not pending_jobs:
                return JsonResponse({
                    'success': True, 
                    'message': 'No pending print jobs found',
                    'jobs_sent': 0
                })

            print(f"🖨️  Auto-print triggered: Found {len(pending_jobs)} pending jobs")
            for job in pending_jobs:
                print(f"   - {job['filename']} (status: {job['metadata']['status']}, completed: {job['metadata']['job_completed']})")

            return JsonResponse({
                'success': True,
                'message': f'Found {len(pending_jobs)} pending print jobs ready for processing',
                'jobs_sent': len(pending_jobs),
                'jobs': pending_jobs
            })

        except Exception as e:
            print(f"Error in auto_print_documents: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@csrf_exempt
def get_vendor_print_jobs(request):
    """
    Fetch print jobs for a specific vendor from vendor_print_jobs/<vendor_id>/
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            vendor_id = data.get('vendor_id')
            if not vendor_id:
                return JsonResponse({'success': False, 'error': 'Missing vendor_id'})

            # Convert vendor_id to string to ensure consistency
            vendor_id = str(vendor_id).strip()

            s3 = boto3.client(
                's3',
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                endpoint_url=settings.R2_ENDPOINT,
                region_name='auto'
            )

            # HARDCODED PATH: Only fetch from vendor_print_jobs/<vendor_id>/
            prefix = f'vendor_print_jobs/{vendor_id}/'
            print(f"🔍 HARDCODED PATH - Searching for jobs in: {prefix}")
            print(f"🔑 Vendor ID: '{vendor_id}' (type: {type(vendor_id)})")

            # First, let's list all objects under vendor_print_jobs/ to debug
            debug_prefix = 'vendor_print_jobs/'
            debug_response = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=debug_prefix)
            print(f"🔍 DEBUG - All vendor folders under {debug_prefix}:")
            for obj in debug_response.get('Contents', []):
                print(f"   📁 {obj['Key']}")

            response = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=prefix)
            jobs = []

            print(f"📊 Response details:")
            print(f"   - IsTruncated: {response.get('IsTruncated', False)}")
            print(f"   - KeyCount: {response.get('KeyCount', 0)}")
            print(f"   - Contents count: {len(response.get('Contents', []))}")

            if 'Contents' not in response or len(response.get('Contents', [])) == 0:
                print(f"📭 No objects found in {prefix}")
                print(f"📊 Available vendors in vendor_print_jobs/:")

                # List all vendor folders for debugging
                vendor_prefix = 'vendor_print_jobs/'
                vendor_response = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=vendor_prefix, Delimiter='/')
                for prefix_info in vendor_response.get('CommonPrefixes', []):
                    folder_name = prefix_info['Prefix'].replace('vendor_print_jobs/', '').rstrip('/')
                    print(f"   📂 Found vendor folder: '{folder_name}'")

                return JsonResponse({
                    'success': True, 
                    'jobs': [],
                    'debug_info': {
                        'searched_prefix': prefix,
                        'vendor_id': vendor_id,
                        'available_vendors': [p['Prefix'].replace('vendor_print_jobs/', '').rstrip('/') 
                                            for p in vendor_response.get('CommonPrefixes', [])]
                    }
                })

            print(f"🎯 Found {len(response.get('Contents', []))} objects in {prefix}")

            for obj in response.get('Contents', []):
                key = obj['Key']
                filename = key.split('/')[-1]

                print(f"🔍 Processing object: {key}")
                print(f"   📄 Filename: '{filename}'")
                print(f"   📏 Size: {obj.get('Size', 0)} bytes")
                print(f"   📅 LastModified: {obj.get('LastModified', 'Unknown')}")

                # Skip folder itself but include all files (even without extensions)
                if not filename or filename == '':
                    print(f"   ⏭️ Skipping empty filename")
                    continue

                try:
                    # Generate download URL first (always works)
                    download_url = s3.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': settings.R2_BUCKET, 'Key': key},
                        ExpiresIn=3600
                    )

                    # Try to get object metadata (might fail for some objects)
                    metadata = {}
                    try:
                        head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                        metadata = head_response.get('Metadata', {})
                        print(f"   ✅ Retrieved metadata: {metadata}")
                    except Exception as meta_error:
                        print(f"   ⚠️ Could not get metadata: {meta_error}")
                        metadata = {}

                    # Create default metadata if none exists
                    if not metadata:
                        print(f"   🔧 Creating default metadata for {filename}")
                        metadata = {
                            'job_completed': 'NO',
                            'status': 'pending',
                            'copies': '1',
                            'color': 'Black and White',
                            'orientation': 'portrait',
                            'pagesize': 'A4',
                            'service_type': 'regular print',
                            'vendor': vendor_id,
                            'user': 'Unknown',
                            'timestamp': obj["LastModified"].isoformat()
                        }

                    # Force job to be pending for processing
                    job_info = {
                        'filename': filename,
                        'download_url': download_url,
                        'r2_path': key,
                        'metadata': {
                            'status': 'no',  # Force status to 'no' for pending jobs
                            'job_completed': 'NO',  # Force to pending
                            'copies': metadata.get('copies', '1'),
                            'color': metadata.get('color', 'Black and White'),
                            'orientation': metadata.get('orientation', 'portrait'),
                            'page_size': metadata.get('pagesize', 'A4'),
                            'pages': metadata.get('pages', '1'),
                            'timestamp': metadata.get('timestamp', obj["LastModified"].isoformat()),
                            'vendor': vendor_id,
                            'user': metadata.get('user', 'Unknown'),
                            'service_type': metadata.get('service_type', 'regular print'),
                            'job_id': metadata.get('job_id', filename.split('.')[0]),
                            'token': metadata.get('token', filename.split('.')[0]),
                            'vendor_id': vendor_id
                        }
                    }

                    jobs.append(job_info)
                    print(f"   ✅ Added job: {filename}")

                except Exception as e:
                    print(f"   ❌ Error processing file {key}: {str(e)}")
                    # Add file anyway with minimal metadata
                    try:
                        download_url = s3.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': settings.R2_BUCKET, 'Key': key},
                            ExpiresIn=3600
                        )

                        job_info = {
                            'filename': filename,
                            'download_url': download_url,
                            'r2_path': key,
                            'metadata': {
                                'status': 'no',
                                'job_completed': 'NO',
                                'copies': '1',
                                'color': 'Black and White',
                                'orientation': 'portrait',
                                'page_size': 'A4',
                                'pages': '1',
                                'timestamp': obj["LastModified"].isoformat(),
                                'vendor': vendor_id,
                                'user': 'Unknown',
                                'service_type': 'regular print',
                                'job_id': filename.split('.')[0],
                                'token': filename.split('.')[0],
                                'vendor_id': vendor_id,
                                'feedback': '',
                                'quality': '',
                                'thickness': '',
                                'service_name': ''
                            }
                        }
                        jobs.append(job_info)
                        print(f"   ⚠️ Added job with minimal metadata: {filename}")
                    except Exception as e2:
                        print(f"   ❌ Failed to create job entry: {e2}")
                        continue

            print(f"📋 FINAL RESULT: Found {len(jobs)} jobs for vendor {vendor_id}")
            for job in jobs:
                print(f"   📄 {job['filename']} - {job['r2_path']}")

            return JsonResponse({'success': True, 'jobs': jobs})

        except Exception as e:
            print(f"❌ Error fetching vendor jobs: {str(e)}")
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid method'})


def get_vendor_specific_print_jobs(vendor_id):
    """Get pending print jobs from vendor-specific folder in R2 storage"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        pending_jobs = []
        vendor_folder_path = f'vendor_print_jobs/{vendor_id}'
        manual_vendor_folder_path = f'vendor_manual_print_jobs/{vendor_id}'

        # Check both vendor print jobs and vendor manual print jobs folders for documents
        try:
            vendor_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=vendor_folder_path)
            manual_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=manual_vendor_folder_path)

            # Combine both object lists
            all_objects = []
            if vendor_objects.get("Contents"):
                all_objects.extend(vendor_objects.get("Contents", []))
            if manual_objects.get("Contents"):
                all_objects.extend(manual_objects.get("Contents", []))

            for obj in all_objects:
                key = obj["Key"]
                filename = key.split("/")[-1]

                # Skip folder itself and non-document files
                if not filename or filename.endswith('.json'):
                    continue

                try:
                    # Get object metadata
                    head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                    metadata = head_response.get('Metadata', {})

                    # Check if job is pending (job_completed = 'NO')
                    job_completed = metadata.get('job_completed', 'NO').upper()
                    status = metadata.get('status', 'pending').lower()

                    if job_completed == 'NO' or status == 'pending':
                        # Generate download URL
                        download_url = s3.generate_presigned_url(
                            ClientMethod='get_object',
                            Params={
                                'Bucket': settings.R2_BUCKET,
                                'Key': key
                            },
                            ExpiresIn=3600
                        )

                        # Build job info
                        job_info = {
                            'filename': filename,
                            'download_url': download_url,
                            'r2_path': key,
                            'user_email': metadata.get('user', ''),
                            'metadata': {
                                'status': 'no',  # Set to 'no' for pending jobs
                                'job_completed': job_completed,
                                'copies': metadata.get('copies', '1'),
                                'color': metadata.get('color', 'Black and White'),
                                'orientation': metadata.get('orientation', 'portrait'),
                                'page_size': metadata.get('pagesize', 'A4'),
                                'pages': metadata.get('pages', '1'),
                                'timestamp': metadata.get('timestamp', obj["LastModified"].isoformat()),
                                'vendor': metadata.get('vendor', vendor_id),
                                'user': metadata.get('user', 'Unknown'),
                                'service_type': metadata.get('service_type', ''),
                                'job_id': metadata.get('job_id', ''),
                                'token': metadata.get('token', ''),
                                'feedback': metadata.get('feedback', ''),
                                'quality': metadata.get('quality', ''),
                                'thickness': metadata.get('thickness', ''),
                                'service_name': metadata.get('service_name', '')
                            }
                        }

                        pending_jobs.append(job_info)
                        print(f"✅ Found pending job for vendor {vendor_id}: {filename}")

                except Exception as e:
                    print(f"Error processing vendor file {key}: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error accessing vendor folder {vendor_folder_path}: {str(e)}")

        print(f"📋 Total pending jobs found for vendor {vendor_id}: {len(pending_jobs)}")
        return pending_jobs

    except Exception as e:
        print(f"Error getting vendor-specific jobs: {e}")
        return []


@csrf_exempt
def update_job_status(request):
    """
    Update job completion status when vendor client completes printing
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            filename = data.get('filename')
            status = data.get('status', 'completed')
            vendor_id = data.get('vendor_id')
            completion_time = data.get('completion_time')

            if not filename:
                return JsonResponse({'success': False, 'error': 'Filename required'})

            # If vendor_id not provided in request, try to get it from session
            if not vendor_id:
                vendor_email = request.session.get('vendor_email')
                if vendor_email:
                    # Get vendor_id from vendor details
                    vendor_details = get_vendor_details_by_email(vendor_email)
                    if vendor_details:
                        # Try to find vendor_id in registration details
                        try:
                            s3 = boto3.client('s3',
                                            aws_access_key_id=settings.R2_ACCESS_KEY,
                                            aws_secret_access_key=settings.R2_SECRET_KEY,
                                            endpoint_url=settings.R2_ENDPOINT,
                                            region_name='auto')

                            reg_key = f'vendor_register_details/{sanitize_email(vendor_email)}/registration_details.json'
                            response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
                            vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                            vendor_id = vendor_data.get('vendor_id', 'vendor1')
                        except:
                            vendor_id = 'vendor1'
                else:
                    vendor_id = 'vendor1'

            # Convert status to job_completed format
            job_completed_status = 'YES' if status.lower() in ['completed', 'yes'] else 'NO'

            # Update the file metadata in R2
            success = update_file_job_status(filename, job_completed_status, vendor_id, completion_time)

            if success:
                print(f"✅ Job status updated by vendor {vendor_id}: {filename} -> {job_completed_status}")
                return JsonResponse({
                    'success': True,
                    'message': f'Job status updated for {filename}',
                    'status': job_completed_status
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to update job status'
                })

        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            print(f"Error updating job status: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


def get_pending_print_jobs():
    """Get pending print jobs from R2 storage with enhanced validation (for admin or dashboard only)"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        pending_jobs = []

        # Check both vendor print jobs and vendor manual print jobs folders for documents
        try:
            vendor_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_print_jobs/')
            manual_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_manual_print_jobs/')

            # Combine both object lists
            all_objects = []
            if vendor_objects.get("Contents"):
                all_objects.extend(vendor_objects.get("Contents", []))
            if manual_objects.get("Contents"):
                all_objects.extend(manual_objects.get("Contents", []))

            for obj in all_objects:
                key = obj["Key"]
                filename = key.split("/")[-1]

                # Skip folder itself and metadata files
                if not filename or filename.lower().endswith('.json'):
                    continue

                # Process files that are in either vendor_print_jobs or vendor_manual_print_jobs folders
                path_parts = key.split('/')
                # Expected structure: vendor_print_jobs/{vendor_id}/{filename} or vendor_manual_print_jobs/{vendor_id}/{filename}
                if len(path_parts) >= 3 and (path_parts[0] == 'vendor_print_jobs' or path_parts[0] == 'vendor_manual_print_jobs'):
                    try:
                        # Get object metadata
                        head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                        metadata = head_response.get('Metadata', {})

                        # Check if job is pending (job_completed = 'NO')
                        job_completed = metadata.get('job_completed', 'NO').upper()
                        status = metadata.get('status', 'pending').lower()
                        service_type = metadata.get('service_type', '').strip().lower()

                        if (job_completed == 'NO' or status == 'pending'):
                            # Generate actual presigned URL for downloading
                            actual_download_url = s3.generate_presigned_url(
                                ClientMethod='get_object',
                                Params={
                                    'Bucket': settings.R2_BUCKET,
                                    'Key': key
                                },
                                ExpiresIn=3600
                            )

                            # Extract vendor info from path
                            vendor_id = path_parts[1] if len(path_parts) > 1 else 'vendor1'

                            # Build job info with proper R2 structure
                            job_info = {
                                'filename': filename,
                                'download_url': actual_download_url,  # Use actual presigned URL for download
                                'r2_path': key,  # Use actual key path
                                'user_email': metadata.get('user', ''),
                                'metadata': {
                                    'status': 'no',  # Set to 'no' for pending jobs
                                    'job_completed': job_completed,
                                    'copies': metadata.get('copies', '1'),
                                    'color': metadata.get('color', 'Black and White'),
                                    'orientation': metadata.get('orientation', 'portrait'),
                                    'page_size': metadata.get('pagesize', 'A4'),
                                    'pages': metadata.get('pages', '1'),
                                    'timestamp': metadata.get('timestamp', obj["LastModified"].isoformat()),
                                    'vendor': metadata.get('vendor', vendor_id),
                                    'user': metadata.get('user', 'Unknown'),
                                    'service_type': metadata.get('service_type', ''),
                                    'job_id': metadata.get('job_id', ''),
                                    'token': metadata.get('token', ''),
                                    'vendor_id': vendor_id,
                                    'feedback': metadata.get('feedback', ''),
                                    'quality': metadata.get('quality', ''),
                                    'thickness': metadata.get('thickness', ''),
                                    'service_name': metadata.get('service_name', '')
                                }
                            }

                            pending_jobs.append(job_info)
                            print(f"✅ Found pending print job for vendor {vendor_id}: {filename} (status: {status}, completed: {job_completed})")

                    except Exception as e:
                        print(f"Error processing vendor file {key}: {str(e)}")
                        continue

        except Exception as e:
            print(f"Error accessing vendor bucket: {str(e)}")

        print(f"📋 Total pending jobs found: {len(pending_jobs)}")
        return pending_jobs

    except Exception as e:
        print(f"Error getting pending jobs: {e}")
        return []

def update_job_status_in_r2(filename, status, vendor_id, user_email, r2_folder_structure):
    """Update job status in R2 storage with enhanced folder structure validation"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        job_completed_status = 'YES' if status.upper() == 'YES' else 'NO'
        updated_files = []
        # Only update vendor-specific folders (no testshop)
        if vendor_id and filename:
            vendor_key = f'vendor_register_details/{vendor_id}/firozshop/{filename}'
            try:
                head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=vendor_key)
                current_metadata = head_response.get('Metadata', {})
                current_metadata['job_completed'] = job_completed_status
                current_metadata['completion_time'] = datetime.datetime.now().isoformat()
                current_metadata['completed_by_vendor'] = vendor_id
                if job_completed_status == 'YES':
                    current_metadata['status'] = 'completed'
                copy_source = {'Bucket': settings.R2_BUCKET, 'Key': vendor_key}
                s3.copy_object(
                    CopySource=copy_source,
                    Bucket=settings.R2_BUCKET,
                    Key=vendor_key,
                    Metadata=current_metadata,
                    MetadataDirective='REPLACE'
                )
                updated_files.append(vendor_key)
                print(f"✅ Updated vendor job status: {vendor_key} -> {job_completed_status}")
            except Exception as e:
                print(f"⚠️  Vendor file {vendor_key} not found or error updating: {str(e)}")
        print(f"📋 Updated {len(updated_files)} file(s) in R2 storage")
        return len(updated_files) > 0
    except Exception as e:
        print(f"❌ Error updating R2 job status: {e}")
        traceback.print_exc()
        return False

def track_job_failure(filename, vendor_id, error_message, user_email):
    """Track job failures with enhanced logging"""
    try:
        # Log failure details
        print(f"Job failure tracked: {filename} by {vendor_id} - {error_message}")

        # Add your failure tracking logic here

        return True

    except Exception as e:
        print(f"Error tracking job failure: {e}")
        traceback.print_exc()
        return False

def update_vendor_status(vendor_id, status, details):
    """Update vendor status with enhanced tracking"""
    try:
        # Update vendor status
        print(f"Vendor status updated: {vendor_id} -> {status}")

        # Add your vendor status update logic here

        return True

    except Exception as e:
        print(f"Error updating vendor status: {e}")
        traceback.print_exc()
        return False

def update_printer_status(vendor_id, printer_stats):
    """Update printer status with enhanced tracking"""
    try:
        # Update printer status
        print(f"Printer status updated for vendor {vendor_id}: {printer_stats}")

        # Add your printer status update logic here

        return True

    except Exception as e:
        print(f"Error updating printer status: {e}")
        traceback.print_exc()
        return False


def update_file_job_status(filename, status='YES', vendor_id=None, completion_time=None):
    """
    Update the job_completed metadata for a specific file in both vendor and user folders
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=settings.R2_ACCESS_KEY,
                      aws_secret_access_key=settings.R2_SECRET_KEY,
                      endpoint_url=settings.R2_ENDPOINT,
                      region_name='auto')

    updated_files = []

    try:
        # Search for the file in vendor folders and user folders
        prefixes_to_search = [
            'vendor_print_jobs/',
            'vendor_manual_print_jobs/',
            'users/'
        ]

        for prefix in prefixes_to_search:
            try:
                # List objects with the prefix
                response = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=prefix)

                for obj in response.get('Contents', []):
                    key = obj['Key']
                    # Check if this is the file we're looking for
                    if key.endswith(filename):
                        try:
                            # Get current object metadata
                            head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                            current_metadata = head_response.get('Metadata', {})

                            # Update job_completed status
                            current_metadata['job_completed'] = status.upper()
                            current_metadata['completion_time'] = datetime.datetime.now().isoformat()

                            # Add vendor information if provided
                            if vendor_id:
                                current_metadata['completed_by_vendor'] = vendor_id

                            # Use provided completion time if available
                            if completion_time:
                                try:
                                    # Convert timestamp to ISO format
                                    completion_dt = datetime.datetime.fromtimestamp(float(completion_time))
                                    current_metadata['completion_time'] = completion_dt.isoformat()
                                except (ValueError, TypeError):
                                    pass  # Use default timestamp if conversion fails

                            # Update status for better tracking
                            if status.upper() == 'YES':
                                current_metadata['status'] = 'completed'

                                # Create notification for job completion
                                user_email = current_metadata.get('user', '')
                                token = current_metadata.get('token', '')
                                service_type = current_metadata.get('service_type', '')

                                if user_email and token:
                                    # Get vendor name
                                    vendor_name = 'PrintMax Vendor'
                                    if vendor_id:
                                        try:
                                            # Try to get vendor details by vendor_id first
                                            vendor_details = get_vendor_details_by_email(vendor_id)
                                            if vendor_details:
                                                vendor_name = vendor_details.get('vendor_name', 'PrintMax Vendor')
                                            else:
                                                # If vendor_id is not an email, try to find vendor by vendor_id
                                                s3 = boto3.client('s3',
                                                                  aws_access_key_id=settings.R2_ACCESS_KEY,
                                                                  aws_secret_access_key=settings.R2_SECRET_KEY,
                                                                  endpoint_url=settings.R2_ENDPOINT,
                                                                  region_name='auto')

                                                # Search for vendor registration with this vendor_id
                                                objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
                                                for obj in objects.get("Contents", []):
                                                    if obj["Key"].endswith('/registration_details.json'):
                                                        try:
                                                            response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                                                            vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                                                            if vendor_data.get('vendor_id') == vendor_id:
                                                                vendor_name = vendor_data.get('vendor_name', 'PrintMax Vendor')
                                                                break
                                                        except:
                                                            continue
                                        except:
                                            pass

                                    # Create notification
                                    create_job_completion_notification(
                                        user_email=user_email,
                                        filename=filename,
                                        token=token,
                                        vendor_name=vendor_name,
                                        service_type=service_type,
                                        completion_time=current_metadata.get('completion_time', datetime.datetime.now().isoformat())
                                    )
                            else:
                                current_metadata['status'] = current_metadata.get('status', 'pending')

                            # Copy object with updated metadata
                            copy_source = {'Bucket': settings.R2_BUCKET, 'Key': key}

                            s3.copy_object(
                                CopySource=copy_source,
                                Bucket=settings.R2_BUCKET,
                                Key=key,
                                Metadata=current_metadata,
                                MetadataDirective='REPLACE'
                            )

                            updated_files.append(key)
                            print(f"✅ Updated job status for {key}: {status}")

                        except Exception as e:
                            print(f"❌ Error updating file {key}: {str(e)}")
                            traceback.print_exc()
                            continue

            except Exception as e:
                print(f"❌ Error searching in {prefix}: {str(e)}")
                traceback.print_exc()
                continue

        if updated_files:
            print(f"📋 Successfully updated {len(updated_files)} file(s) in R2 storage")
            return True
        else:
            print(f"⚠️ No files found with filename: {filename}")
            return False

    except Exception as e:
        print(f"❌ Error updating job status for {filename}: {str(e)}")
        traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────
# FILE UPLOAD TO CLOUDFLARE R2
# ─────────────────────────────────────────────────────────────

@csrf_exempt  # Use proper CSRF protection in production!
def upload_to_r2(request):
    if request.method == 'POST':
        try:
            files_uploaded = 0
            file_count = int(request.POST.get('file_count', 0))
            selected_vendor = request.POST.get('selected_vendor', 'firozshop')
            vendor_id = request.POST.get('vendor_id') or get_vendor_id_by_shop_folder(selected_vendor)

            # Initialize S3 client
            s3 = boto3.client('s3',
                              aws_access_key_id=settings.R2_ACCESS_KEY,
                              aws_secret_access_key=settings.R2_SECRET_KEY,
                              endpoint_url=settings.R2_ENDPOINT,
                              region_name='auto')

            # Get user email for folder creation
            user_email = request.user.email if request.user.is_authenticated else 'anonymous'

            # Process each file with its corresponding settings
            for i in range(file_count):
                file_key = f'file_{i}'
                settings_key = f'settings_{i}'

                if file_key in request.FILES and settings_key in request.POST:
                    # Get the file
                    file = request.FILES[file_key]
                    file_content = file.read()

                    # Get and parse the settings JSON
                    settings_json = request.POST.get(settings_key)
                    print_settings = json.loads(settings_json)

                    # Generate a unique 3-digit token for this job
                    token = str(random.randint(100, 999))

                    # Generate a unique job_id for this file (use original_filename + timestamp for idempotency)
                    job_id = print_settings.get('job_id')
                    if not job_id:
                        job_id = str(uuid.uuid4())
                        print_settings['job_id'] = job_id

                    # Determine content type
                    content_type = file.content_type or 'application/octet-stream'

                    # Get file extension for better content type detection
                    file_extension = file.name.split('.')[-1].lower() if '.' in file.name else ''

                    # Build file metadata
                    file_metadata = {
                        'copies': str(print_settings.get("copies", "1")),
                        'color': print_settings.get("color", "Black and White"),
                        'orientation': print_settings.get("orientation", "portrait"),
                        'pageRange': str(print_settings.get("pageRange", "")),
                        'specificPages': str(print_settings.get("specificPages", "")),
                        'pageSize': str(print_settings.get("pageSize", "A4")),
                        'spiralBinding': str(print_settings.get("spiralBinding", "No")),
                        'lamination': str(print_settings.get("lamination", "No")),
                        'timestamp': datetime.datetime.now().isoformat(),
                        'status': 'pending',
                        'job_completed': 'NO',
                        'trash': 'NO',
                        'user': user_email,
                        'vendor': vendor_id,
                        'job_id': job_id,
                        'service_type': print_settings.get('service_type', 'regular print'),
                        'token': token,
                        'feedback': print_settings.get('feedback', ''),
                        'quality': print_settings.get('quality', ''),
                        'thickness': print_settings.get('thickness', ''),
                        'service_name': print_settings.get('service_name', '')
                    }

                    # Check if this is a photo print service
                    service_type = print_settings.get('service_type', '')
                    # Always use the same storage folders as the userdashboard print modal
                    vendor_file_key = f'vendor_print_jobs/{vendor_id}/{file.name}'
                    user_file_key = f'users/{user_email}/{file.name}'

                    if service_type in ['photo_print', 'passport_photo']:
                        # If the uploaded file is a PDF, just upload it directly (from jsPDF frontend)
                        if file.name.lower().endswith('.pdf') or file.content_type == 'application/pdf':
                            # Use the same keys as above
                            s3.put_object(
                                Bucket=settings.R2_BUCKET,
                                Key=vendor_file_key,
                                Body=file_content,
                                ContentType='application/pdf',
                                Metadata=file_metadata
                            )
                            s3.put_object(
                                Bucket=settings.R2_BUCKET,
                                Key=user_file_key,
                                Body=file_content,
                                ContentType='application/pdf',
                                Metadata=file_metadata
                            )
                            print(f"✅ PDF uploaded directly: {file.name}")
                        else:
                            # Handle photo print processing (backend layout generation)
                            print(f"📸 Processing {service_type} service...")
                            # Collect all image files for this job
                            image_files_data = []
                            for j in range(file_count):
                                if f'file_{j}' in request.FILES:
                                    temp_file = request.FILES[f'file_{j}']
                                    if temp_file.content_type and temp_file.content_type.startswith('image/'):
                                        image_files_data.append(temp_file.read())
                            if not image_files_data:
                                image_files_data = [file_content]  # Use current file if no other images
                            # Create layout configuration
                            layout_config = {
                                'photo_count': int(print_settings.get('photo_count', 1)),
                                'layout': print_settings.get('layout', '1x1'),
                                'image_mode': print_settings.get('image_mode', 'same'),
                                'color': print_settings.get('color', 'Color'),
                                'paper_size': print_settings.get('paper_size', 'A4')
                            }
                            # Create photo layout PDF
                            if service_type == 'passport_photo':
                                # Get country and package from settings
                                country = print_settings.get('country', 'India')
                                total_prints = int(print_settings.get("copies", 8))
                                
                                print(f"🔍 Processing passport photo: Country={country}, Prints={total_prints}")

                                # Country-specific passport photo processing
                                pdf_data = create_passport_photo_layout(file_content, total_prints, country)
                            else:
                                # New photo print layout
                                pdf_data = create_photo_print_layout(image_files_data, layout_config)
                            if pdf_data:
                                # Update file metadata for photo service
                                if service_type == 'passport_photo':
                                    file_metadata.update({
                                        'service_type': service_type,
                                        'photo_count': str(total_prints),
                                        'country': country,
                                        'layout_created': 'YES',
                                        'original_filename': file.name,
                                        'paper_size': 'A4',
                                        'photo_dimensions': get_passport_photo_dimensions(country)
                                    })
                                else:
                                    file_metadata.update({
                                        'service_type': service_type,
                                        'photo_count': str(layout_config['photo_count']),
                                        'layout': layout_config['layout'],
                                        'image_mode': layout_config['image_mode'],
                                        'layout_created': 'YES',
                                        'original_filename': file.name,
                                        'paper_size': layout_config['paper_size']
                                    })
                                # Use the same keys as above
                                s3.put_object(
                                    Bucket=settings.R2_BUCKET,
                                    Key=vendor_file_key,
                                    Body=pdf_data,
                                    ContentType='application/pdf',
                                    Metadata=file_metadata
                                )
                                s3.put_object(
                                    Bucket=settings.R2_BUCKET,
                                    Key=user_file_key,
                                    Body=pdf_data,
                                    ContentType='application/pdf',
                                    Metadata=file_metadata
                                )
                                print(f"✅ Photo layout saved as PDF: {file.name}")
                            else:
                                print(f"❌ Failed to create {service_type} layout")
                                return JsonResponse({'success': False, 'error': f'Failed to create {service_type} layout'}, status=500)
                    else:
                        # Regular file upload for non-passport services
                        s3.put_object(
                            Bucket=settings.R2_BUCKET,
                            Key=vendor_file_key,
                            Body=file_content,
                            ContentType=content_type,
                            Metadata=file_metadata
                        )
                        s3.put_object(
                            Bucket=settings.R2_BUCKET,
                            Key=user_file_key,
                            Body=file_content,
                            ContentType=content_type,
                            Metadata=file_metadata
                        )

                    files_uploaded += 1

            if files_uploaded > 0:
                return JsonResponse({
                    'success': True,
                    'message': f'{files_uploaded} file(s) uploaded successfully'
                })
            else:
                return JsonResponse({'success': False, 'error': 'No files uploaded'}, status=400)

        except json.JSONDecodeError as e:
            return JsonResponse({'success': False, 'error': f'Invalid JSON in settings: {str(e)}'}, status=400)
        except Exception as e:
            print(f"Upload error: {str(e)}")
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


# ─────────────────────────────────────────────────────────────
# LIST OBJECTS IN CLOUDFLARE R2
# ─────────────────────────────────────────────────────────────


def list_r2_files():
    s3 = boto3.client('s3',
                      aws_access_key_id=settings.R2_ACCESS_KEY,
                      aws_secret_access_key=settings.R2_SECRET_KEY,
                      endpoint_url=settings.R2_ENDPOINT,
                      region_name='auto')
    try:
        file_data = []
        vendor_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_print_jobs/')
        manual_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_manual_print_jobs/')
        all_objects = []
        if vendor_objects.get("Contents"):
            all_objects.extend(vendor_objects.get("Contents", []))
        if manual_objects.get("Contents"):
            all_objects.extend(manual_objects.get("Contents", []))
        for obj in all_objects:
            key = obj["Key"]
            filename = key.split("/")[-1]
            if filename.lower().endswith('.json') or not filename:
                continue
            path_parts = key.split('/')
            if len(path_parts) >= 3 and (path_parts[0] == 'vendor_print_jobs' or path_parts[0] == 'vendor_manual_print_jobs'):
                try:
                    head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                    metadata = head_response.get('Metadata', {})
                    job_completed = metadata.get('job_completed', 'NO').upper()
                    if job_completed not in ['NO', 'YES']:
                        continue
                    url = s3.generate_presigned_url(
                        ClientMethod='get_object',
                        Params={
                            'Bucket': settings.R2_BUCKET,
                            'Key': key
                        },
                        ExpiresIn=3600
                    )
                    download_url = s3.generate_presigned_url(
                        ClientMethod='get_object',
                        Params={
                            'Bucket': settings.R2_BUCKET,
                            'Key': key,
                            'ResponseContentDisposition': f'inline; filename="{filename}"'
                        },
                        ExpiresIn=3600
                    )
                    file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
                    file_type = get_file_type(file_extension)
                    pages = metadata.get('pages', estimate_pages_from_size(obj.get('Size', 0), file_extension))
                    vendor_id = path_parts[1] if len(path_parts) > 1 else 'vendor1'
                    file_info = {
                        "filename": filename,
                        "job_id": metadata.get('job_id', ''),
                        "preview_url": url,
                        "download_url": download_url,
                        "file_type": file_type,
                        "file_extension": file_extension,
                        "size": format_file_size(obj.get('Size', 0)),
                        "user": metadata.get('user', 'Auto User'),
                        "pages": pages,
                        "status": metadata.get('status', 'pending').title(),
                        "uploaded_at": obj["LastModified"].strftime("%Y-%m-%d %H:%M"),
                        "priority": metadata.get('priority', 'Medium'),
                        "copies": metadata.get('copies', '1'),
                        "color": metadata.get('color', 'Black and White'),
                        "orientation": metadata.get('orientation', 'portrait'),
                        "pageRange": metadata.get('pagerange', 'all'),
                        "specificPages": metadata.get('specificpages', ''),
                        "pageSize": metadata.get('pagesize', 'A4'),
                        "spiralBinding": metadata.get('spiralbinding', 'No'),
                        "lamination": metadata.get('lamination', 'No'),
                        "job_completed": metadata.get('job_completed', 'NO'),
                        "trash": metadata.get('trash', 'NO'),
                        "timestamp": metadata.get('timestamp', obj["LastModified"].isoformat()),
                        "service_type": metadata.get('service_type', ''),
                        "service_name": metadata.get('service_name', ''),
                        "token": metadata.get('token', ''),
                        "vendor_id": vendor_id,
                        "feedback": metadata.get('feedback', ''),
                        "quality": metadata.get('quality', ''),
                        "thickness": metadata.get('thickness', '')
                    }
                    file_info["print_options"] = f"{file_info['copies']} copies, {file_info['color']}, {file_info['orientation']}"
                    file_data.append(file_info)
                except Exception as e:
                    print(f"Error processing vendor file {key}: {str(e)}")
                    continue
        return file_data
    except Exception as e:
        print(f"Error listing R2 files: {str(e)}")
        return []

def get_file_type(extension):
    """Get file type based on extension"""
    file_types = {
        'pdf': 'PDF Document',
        'doc': 'Word Document',
        'docx': 'Word Document',
        'txt': 'Text Document',
        'ppt': 'PowerPoint Presentation',
        'pptx': 'PowerPoint Presentation',
        'xls': 'Excel Spreadsheet',
        'xlsx': 'Excel Spreadsheet',
        'jpg': 'JPEG Image',
        'jpeg': 'JPEG Image',
        'png': 'PNG Image',
        'gif': 'GIF Image',
        'bmp': 'BMP Image',
        'tiff': 'TIFF Image',
        'svg': 'SVG Image'
    }
    return file_types.get(extension, 'Document')

def estimate_pages_from_size(file_size, file_extension):
    """Estimate number of pages based on file size and type with improved accuracy"""
    # Convert bytes to KB
    size_kb = file_size / 1024

    # Different estimation for different file types
    if file_extension.lower() in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'svg']:
        return 1  # Images are typically 1 page
    elif file_extension.lower() == 'pdf':
        # PDFs: More accurate estimation based on typical PDF compression
        if size_kb < 50:
            return 1
        elif size_kb < 200:
            return max(1, round(size_kb / 50))  # Small PDFs have less compression
        elif size_kb < 1000:
            return max(1, round(size_kb / 80))  # Medium PDFs
        else:
            return max(1, round(size_kb / 120))  # Large PDFs have better compression
    elif file_extension.lower() in ['doc', 'docx']:
        # Word docs: More accurate estimation
        if size_kb < 100:
            return max(1, round(size_kb / 30))
        else:
            return max(1, round(size_kb / 60))
    elif file_extension.lower() in ['ppt', 'pptx']:
        # PowerPoint: More conservative estimation
        return max(1, round(size_kb / 150))
    elif file_extension.lower() in ['xls', 'xlsx']:
        # Excel: Better estimation based on typical spreadsheet size
        return max(1, round(size_kb / 60))
    elif file_extension.lower() == 'txt':
        # Text files: Very accurate estimation
        return max(1, round(size_kb / 3))  # Assuming ~3KB per page of text
    else:
        # Other files: conservative estimate
        return max(1, round(size_kb / 50))

def format_file_size(size_bytes):
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"


def create_photo_print_layout(input_images_data, layout_config):
    """
    Create a photo print layout with dynamic grid arrangements on A4 page as PDF.
    Args:
        input_images_data (list): List of input image data (bytes)
        layout_config (dict): Layout configuration with grid info and settings
    Returns:
        bytes: PDF data of the layout, None if failed
    """
    try:
        total_prints = layout_config.get('photo_count', 1)
        layout_type = str(layout_config.get('layout', '1'))
        image_mode = layout_config.get('image_mode', 'same')

        print(f"📸 Creating photo print layout for {total_prints} photos in {layout_type} arrangement...")

        # A4 dimensions at 300 DPI for high quality printing
        A4_WIDTH = 2480   # 210mm at 300 DPI
        A4_HEIGHT = 3508  # 297mm at 300 DPI
        MARGIN = 118      # 10mm margins
        SPACING = 59      # 5mm spacing between photos

        # Determine grid layout based on photo count
        if total_prints == 1:
            cols, rows = 1, 1
        elif total_prints == 2:
            cols, rows = 1, 2
        elif total_prints == 4:
            cols, rows = 2, 2
        elif total_prints == 6:
            cols, rows = 2, 3
        elif total_prints == 9:
            cols, rows = 3, 3
        else:
            cols, rows = 1, 1

        actual_photos = min(total_prints, cols * rows)

        # Calculate photo dimensions based on grid layout
        available_width = A4_WIDTH - (2 * MARGIN) - ((cols - 1) * SPACING)
        available_height = A4_HEIGHT - (2 * MARGIN) - ((rows - 1) * SPACING)
        photo_width = available_width // cols
        photo_height = available_height // rows

        # Load and process images
        print("📂 Loading and processing images...")
        processed_images = []

        for i, image_data in enumerate(input_images_data):
            if i >= actual_photos:
                break

            original_image = Image.open(io.BytesIO(image_data))
            if original_image.mode != 'RGB':
                original_image = original_image.convert('RGB')

            # Resize image to fit photo dimensions while maintaining aspect ratio
            original_width, original_height = original_image.size
            scale_width = photo_width / original_width
            scale_height = photo_height / original_height
            scale = min(scale_width, scale_height)

            new_width = int(original_width * scale)
            new_height = int(original_height * scale)
            resized_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Create photo with white background and centered image
            photo = Image.new('RGB', (photo_width, photo_height), 'white')
            x_offset = (photo_width - new_width) // 2
            y_offset = (photo_height - new_height) // 2
            photo.paste(resized_image, (x_offset, y_offset))
            processed_images.append(photo)

        # If same image mode and we have only one image, replicate it
        if image_mode == 'same' and len(processed_images) == 1:
            single_image = processed_images[0]
            processed_images = [single_image.copy() for _ in range(actual_photos)]

        # Ensure we have enough images for the layout
        while len(processed_images) < actual_photos:
            if len(processed_images) > 0:
                processed_images.append(processed_images[0].copy())
            else:
                # Create a placeholder image if no images available
                placeholder = Image.new('RGB', (photo_width, photo_height), 'lightgray')
                processed_images.append(placeholder)

        # Create the A4 layout with white background
        print(f"📄 Creating A4 layout with {actual_photos} photos in {cols}x{rows} grid...")
        layout = Image.new('RGB', (A4_WIDTH, A4_HEIGHT), 'white')

        # Calculate positioning to center the grid on the page
        total_width = cols * photo_width + (cols - 1) * SPACING
        total_height = rows * photo_height + (rows - 1) * SPACING
        start_x = max(MARGIN, (A4_WIDTH - total_width) // 2)
        start_y = max(MARGIN, (A4_HEIGHT - total_height) // 2)

        # Place photos on the layout
        photo_index = 0
        for row in range(rows):
            for col in range(cols):
                if photo_index >= actual_photos or photo_index >= len(processed_images):
                    break
                x = start_x + col * (photo_width + SPACING)
                y = start_y + row * (photo_height + SPACING)
                layout.paste(processed_images[photo_index], (x, y))
                photo_index += 1

        # Add subtle corner marks for cutting guidance
        draw = ImageDraw.Draw(layout)
        mark_length = 20  # Corner mark length
        mark_color = 'lightgray'  # Light gray for subtle guides
        mark_width = 1  # Thin lines

        for row in range(rows):
            for col in range(cols):
                if (row * cols + col) >= actual_photos:
                    break
                x = start_x + col * (photo_width + SPACING)
                y = start_y + row * (photo_height + SPACING)

                # Corner marks for cutting guidance
                offset = 4  # Distance from photo edge

                # Top-left corner
                draw.line([(x-offset, y-offset), (x-offset+mark_length, y-offset)], fill=mark_color, width=mark_width)
                draw.line([(x-offset, y-offset), (x-offset, y-offset+mark_length)], fill=mark_color, width=mark_width)

                # Top-right corner
                draw.line([(x+photo_width+offset-mark_length, y-offset), (x+photo_width+offset, y-offset)], fill=mark_color, width=mark_width)
                draw.line([(x+photo_width+offset, y-offset), (x+photo_width+offset, y-offset+mark_length)], fill=mark_color, width=mark_width)

                # Bottom-left corner
                draw.line([(x-offset, y+photo_height+offset-mark_length), (x-offset, y+photo_height+offset)], fill=mark_color, width=mark_width)
                draw.line([(x-offset, y+photo_height+offset), (x-offset+mark_length, y+photo_height+offset)], fill=mark_color, width=mark_width)

                # Bottom-right corner
                draw.line([(x+photo_width+offset, y+photo_height+offset-mark_length), (x+photo_width+offset, y+photo_height+offset)], fill=mark_color, width=mark_width)
                draw.line([(x+photo_width+offset-mark_length, y+photo_height+offset), (x+photo_width+offset, y+photo_height+offset)], fill=mark_color, width=mark_width)

        # Convert to high-quality PDF with proper settings
        print("💾 Converting layout to PDF...")
        pdf_buffer = io.BytesIO()

        # Save as PDF with high quality settings for printing
        layout.save(
            pdf_buffer, 
            'PDF', 
            quality=95,  # High quality
            resolution=300.0,  # 300 DPI for print quality
            optimize=False  # Don't optimize to maintain quality
        )

        pdf_data = pdf_buffer.getvalue()
        pdf_buffer.close()

        print(f"✅ Photo print layout created successfully!")
        print(f"   📄 {actual_photos} photos arranged on A4 page")
        print(f"   📐 Grid layout: {cols}x{rows}")
        print(f"   🖼️ Image mode: {image_mode}")
        print(f"   🎨 High quality 300 DPI PDF ready for printing")

        return pdf_data

    except Exception as e:
        print(f"❌ Error creating photo print layout: {e}")
        traceback.print_exc()
        return None


def create_passport_photo_layout(input_image_data, total_prints=8, country='India'):
    """
    Creates passport photo layout based on selected country and specified print count
    """
    try:
        # Country-specific configurations with exact dimensions
        country_config = {
            'India': {'size': (35, 45), 'unit': 'mm', 'prints': [8, 16, 30]},
            'United Arab Emirates (UAE)': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'Saudi Arabia': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'United States': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'Singapore': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Thailand': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'United Kingdom': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Qatar': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'Kuwait': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'Canada': {'size': (50, 70), 'unit': 'mm', 'prints': [8]},
            'Australia': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Maldives': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'Nepal': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Sri Lanka': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Malaysia': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Indonesia': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'Switzerland': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Bhutan': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Mauritius': {'size': (51, 51), 'unit': 'mm', 'prints': [8]},
            'France': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
            'Germany': {'size': (35, 45), 'unit': 'mm', 'prints': [8]},
        }

        selected_config = country_config.get(country, country_config['India'])
        photo_width_mm, photo_height_mm = selected_config['size']

        # Validate print count based on country
        if country == 'India':
            if total_prints not in selected_config['prints']:
                total_prints = 8
        else:
            total_prints = 8

        print(f"📸 Creating passport photo layout for {country}")
        print(f"   📏 Photo size: {photo_width_mm}x{photo_height_mm}mm")
        print(f"   📊 Total prints: {total_prints}")

        # Convert mm to pixels at 300 DPI (11.811 pixels per mm)
        DPI_CONVERSION = 11.811
        photo_width_px = int(photo_width_mm * DPI_CONVERSION)
        photo_height_px = int(photo_height_mm * DPI_CONVERSION)

        # A4 dimensions at 300 DPI
        A4_WIDTH = 2480   # 210mm at 300 DPI
        A4_HEIGHT = 3508  # 297mm at 300 DPI
        MARGIN = 118      # 10mm margins
        SPACING = 59      # 5mm spacing between photos

        # Calculate optimal grid layout for 8 photos (always 2x4 for consistent layout)
        cols, rows = 2, 4

        print(f"📄 Creating {cols}x{rows} grid layout")

        # Load and process the input image
        original_image = Image.open(io.BytesIO(input_image_data))
        if original_image.mode != 'RGB':
            original_image = original_image.convert('RGB')

        # Resize image to passport photo dimensions while maintaining aspect ratio
        original_width, original_height = original_image.size
        scale_width = photo_width_px / original_width
        scale_height = photo_height_px / original_height
        scale = min(scale_width, scale_height)

        new_width = int(original_width * scale)
        new_height = int(original_height * scale)
        resized_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Create passport photo with white background and centered image
        passport_photo = Image.new('RGB', (photo_width_px, photo_height_px), 'white')
        x_offset = (photo_width_px - new_width) // 2
        y_offset = (photo_height_px - new_height) // 2
        passport_photo.paste(resized_image, (x_offset, y_offset))

        # Create the A4 layout with white background
        layout = Image.new('RGB', (A4_WIDTH, A4_HEIGHT), 'white')

        # Calculate positioning to center the grid on the page
        total_width = cols * photo_width_px + (cols - 1) * SPACING
        total_height = rows * photo_height_px + (rows - 1) * SPACING
        start_x = max(MARGIN, (A4_WIDTH - total_width) // 2)
        start_y = max(MARGIN, (A4_HEIGHT - total_height) // 2)

        # Place photos on the layout
        photo_count = 0
        for row in range(rows):
            for col in range(cols):
                if photo_count >= total_prints:
                    break
                x = start_x + col * (photo_width_px + SPACING)
                y = start_y + row * (photo_height_px + SPACING)
                layout.paste(passport_photo, (x, y))
                photo_count += 1

        # Add cutting guides (corner marks)
        draw = ImageDraw.Draw(layout)
        mark_length = 20
        mark_color = 'lightgray'
        mark_width = 1

        for row in range(rows):
            for col in range(cols):
                if (row * cols + col) >= total_prints:
                    break
                x = start_x + col * (photo_width_px + SPACING)
                y = start_y + row * (photo_height_px + SPACING)

                # Corner marks for cutting guidance
                offset = 4

                # Top-left corner
                draw.line([(x-offset, y-offset), (x-offset+mark_length, y-offset)], fill=mark_color, width=mark_width)
                draw.line([(x-offset, y-offset), (x-offset, y-offset+mark_length)], fill=mark_color, width=mark_width)

                # Top-right corner
                draw.line([(x+photo_width_px+offset-mark_length, y-offset), (x+photo_width_px+offset, y-offset)], fill=mark_color, width=mark_width)
                draw.line([(x+photo_width_px+offset, y-offset), (x+photo_width_px+offset, y-offset+mark_length)], fill=mark_color, width=mark_width)

                # Bottom-left corner
                draw.line([(x-offset, y+photo_height_px+offset-mark_length), (x-offset, y+photo_height_px+offset)], fill=mark_color, width=mark_width)
                draw.line([(x-offset, y+photo_height_px+offset), (x-offset+mark_length, y+photo_height_px+offset)], fill=mark_color, width=mark_width)

                # Bottom-right corner
                draw.line([(x+photo_width_px+offset, y+photo_height_px+offset-mark_length), (x+photo_width_px+offset, y+photo_height_px+offset)], fill=mark_color, width=mark_width)
                draw.line([(x+photo_width_px+offset-mark_length, y+photo_height_px+offset), (x+photo_width_px+offset, y+photo_height_px+offset)], fill=mark_color, width=mark_width)

        # Convert to PDF
        pdf_buffer = io.BytesIO()
        layout.save(
            pdf_buffer, 
            'PDF', 
            quality=95,
            resolution=300.0,
            optimize=False
        )

        pdf_data = pdf_buffer.getvalue()
        pdf_buffer.close()

        print(f"✅ Passport photo layout created successfully!")
        print(f"   📄 {total_prints} photos of {photo_width_mm}x{photo_height_mm}mm each")
        print(f"   🏁 Country: {country}")
        print(f"   🎨 High quality 300 DPI PDF ready for printing")

        return pdf_data

    except Exception as e:
        print(f"❌ Error creating passport photo layout: {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────────────────────────
# HANDLE 'PROCEED TO PRINT' – FILE + SETTINGS
# ─────────────────────────────────────────────────────────────


@csrf_exempt
def process_print_request(request):
    if request.method == 'POST':
        try:
            file_count = int(request.POST.get('file_count', 0))
            files_processed = 0

            # Process each file with its corresponding settings
            for i in range(file_count):
                file_key = f'file_{i}'
                settings_key = f'settings_{i}'

                if file_key in request.FILES and settings_key in request.POST:
                    # Get the file
                    file = request.FILES[file_key]
                    file_content = file.read()

                    # Get and parse the settings JSON
                    settings_json = request.POST.get(settings_key)
                    print_settings = json.loads(settings_json)

                    # Use settings from the parsed JSON for metadata
                    file_name = file.name

                    # Initialize S3 client
                    s3 = boto3.client('s3',
                                      aws_access_key_id=settings.R2_ACCESS_KEY,
                                      aws_secret_access_key=settings.R2_SECRET_KEY,
                                      endpoint_url=settings.R2_ENDPOINT,
                                      region_name='auto')

                    # Upload the original file with metadata
                    s3.put_object(Bucket=settings.R2_BUCKET,
                                  Key=file_name,
                                  Body=file_content,
                                  ContentType=file.content_type,
                                  Metadata={
                                      'copies': str(print_settings.get("copies", "1")),
                                      'color': print_settings.get("color", "Black and White"),
                                      'orientation': print_settings.get("orientation", "portrait"),
                                      'pageRange': str(print_settings.get("pageRange", "")),
                                      'specificPages': str(print_settings.get("specificPages", "")),
                                      'pageSize': str(print_settings.get("pageSize", "A4")),
                                      'spiralBinding': str(print_settings.get("spiralBinding", "No")),
                                      'lamination': str(print_settings.get("lamination", "No")),
                                      'timestamp': datetime.datetime.now().isoformat(),
                                      'status': 'pending',
                                      'job_completed': 'NO',
                                      'trash': 'NO'
                                  })

                    files_processed += 1

            return JsonResponse({'success': True})
        except Exception as e:
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


from django.shortcuts import render
from django.conf import settings

def sign_in(request):
    client_id = settings.GOOGLE_CLIENT_ID
    print(f"🔍 Debug: Google Client ID loaded: {client_id[:20] if client_id else 'None'}...")
    return render(request, 'login.html', {'client_id': client_id})

from django.http import JsonResponse
from django.contrib.auth import login
from django.contrib.auth.models import User
import requests

def auth_receiver(request):
    if request.method == 'POST':
        token = request.POST.get('credential')
        # Verify the token with Google
        response = requests.get(
            'https://www.googleapis.com/oauth2/v3/tokeninfo',
            params={'id_token': token}
        )
        data = response.json()
        if 'sub' in data:  # 'sub' is the unique Google user ID
            email = data['email']
            google_user_id = data['sub']

            # Store the raw authentication details in R2 storage
            try:
                s3 = boto3.client('s3',
                                  aws_access_key_id=settings.R2_ACCESS_KEY,
                                  aws_secret_access_key=settings.R2_SECRET_KEY,
                                  endpoint_url=settings.R2_ENDPOINT,
                                  region_name='auto')

                file_content = json.dumps(data, indent=4)
                file_key = f"signupdetails/{google_user_id}.json"

                s3.put_object(Bucket=settings.R2_BUCKET,
                              Key=file_key,
                              Body=file_content,
                              ContentType='application/json')

                print(f"✅ Successfully stored signup details for {email} in R2.")

            except Exception as e:
                print(f"❌ Error storing signup details in R2: {str(e)}")
                traceback.print_exc()

            # Find or create user
            user, created = User.objects.get_or_create(
                username=email,
                defaults={'email': email}
            )
            login(request, user)
            return JsonResponse({'status': 'success', 'email': email})
        return JsonResponse({'status': 'error', 'message': 'Invalid token'}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


def get_passport_photo_dimensions(country):
    """Get passport photo dimensions for a specific country"""
    country_config = {
        'India': '35x45mm',
        'United Arab Emirates (UAE)': '51x51mm',
        'Saudi Arabia': '51x51mm',
        'United States': '51x51mm',
        'Singapore': '35x45mm',
        'Thailand': '35x45mm',
        'United Kingdom': '35x45mm',
        'Qatar': '51x51mm',
        'Kuwait': '51x51mm',
        'Canada': '50x70mm',
        'Australia': '35x45mm',
        'Maldives': '51x51mm',
        'Nepal': '35x45mm',
        'Sri Lanka': '35x45mm',
        'Malaysia': '35x45mm',
        'Indonesia': '51x51mm',
        'Switzerland': '35x45mm',
        'Bhutan': '35x45mm',
        'Mauritius': '51x51mm',
        'France': '35x45mm',
        'Germany': '35x45mm',
    }
    return country_config.get(country, '35x45mm')


def photoprint(request):
    """
    Render the photo print page
    """
    return render(request, 'photoprint.html')


# ─────────────────────────────────────────────────────────────
# VENDOR REGISTRATION AND PRICING VIEWS
# ─────────────────────────────────────────────────────────────

def vendor_register(request):
    """
    Render the vendor registration page
    """
    return render(request, 'vendor_register.html')


@csrf_exempt
def vendor_pricing(request):
    """
    Render the pricing form on GET, handle pricing submission on POST.
    """
    if request.method == 'GET':
        # Get vendor email from URL parameters
        vendor_email = request.GET.get('vendorEmail')
        
        # If vendor email is provided, fetch vendor details
        vendor_details = None
        if vendor_email:
            try:
                s3 = boto3.client('s3',
                                  aws_access_key_id=settings.R2_ACCESS_KEY,
                                  aws_secret_access_key=settings.R2_SECRET_KEY,
                                  endpoint_url=settings.R2_ENDPOINT,
                                  region_name='auto')
                
                key = f'vendor_register_details/{sanitize_email(vendor_email)}/registration_details.json'
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                vendor_details = json.loads(response['Body'].read().decode('utf-8'))
            except Exception as e:
                print(f"❌ Error fetching vendor details: {str(e)}")
                vendor_details = None
        
        # Check if load_pricing parameter is present
        load_pricing = request.GET.get('load_pricing')
        pricing_data = None
        
        if load_pricing and vendor_email:
            try:
                # Try to load existing pricing data
                pricing_key = f'vendor_register_details/{sanitize_email(vendor_email)}/pricing.json'
                s3 = boto3.client('s3',
                                  aws_access_key_id=settings.R2_ACCESS_KEY,
                                  aws_secret_access_key=settings.R2_SECRET_KEY,
                                  endpoint_url=settings.R2_ENDPOINT,
                                  region_name='auto')
                
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=pricing_key)
                pricing_data = json.loads(response['Body'].read().decode('utf-8'))
            except Exception as e:
                print(f"ℹ️ No existing pricing data found for {vendor_email}: {str(e)}")
                pricing_data = None
        
        context = {
            'vendor_email': vendor_email,
            'vendor_details': vendor_details,
            'pricing_data': pricing_data
        }
        return render(request, 'vendor_pricing.html', context)
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            vendor_email = data.get('vendor_email') or data.get('email') or data.get('vendor_id')
            pricing_entries = data.get('pricing_entries', [])

            if not vendor_email:
                return JsonResponse({'success': False, 'message': 'Vendor email required'})

            # Initialize S3 client
            s3 = boto3.client('s3',
                              aws_access_key_id=settings.R2_ACCESS_KEY,
                              aws_secret_access_key=settings.R2_SECRET_KEY,
                              endpoint_url=settings.R2_ENDPOINT,
                              region_name='auto')

            # Categorize pricing data by service type
            pricing_entries = data.get('pricing_entries', [])
            categorized_pricing = {
                'digital_print': {},
                'jumbo_print': {},
                'gloss_print': {},
                'photo_print': {},
                'golden_embossing': {},
                'passport_photo': {},
                'a4_print': {},
                'lamination': {},
                'binding': {}
            }
            
            # Organize pricing entries by service category
            for entry in pricing_entries:
                service_type = entry.get('service_type', '')
                price = entry.get('price', 0)
                
                # Categorize based on service type prefix
                if service_type.startswith('digital_print'):
                    categorized_pricing['digital_print'][service_type] = price
                elif service_type.startswith('jumbo_print'):
                    categorized_pricing['jumbo_print'][service_type] = price
                elif service_type.startswith('gloss_print'):
                    categorized_pricing['gloss_print'][service_type] = price
                elif service_type.startswith('photo_print'):
                    categorized_pricing['photo_print'][service_type] = price
                elif service_type.startswith('emboss'):
                    categorized_pricing['golden_embossing'][service_type] = price
                elif service_type.startswith('passport_photo'):
                    categorized_pricing['passport_photo'][service_type] = price
                elif service_type.startswith('a4_print'):
                    categorized_pricing['a4_print'][service_type] = price
                elif service_type.startswith('lamination'):
                    categorized_pricing['lamination'][service_type] = price
                elif service_type.startswith('binding'):
                    categorized_pricing['binding'][service_type] = price
                else:
                    # Fallback to general category
                    if 'general' not in categorized_pricing:
                        categorized_pricing['general'] = {}
                    categorized_pricing['general'][service_type] = price
            
            # Prepare pricing data with categorized structure
            pricing_data = {
                'vendor_email': vendor_email,
                'pricing_data': data.get('pricing_data', {}),  # Keep original for backward compatibility
                'categorized_pricing': categorized_pricing,
                'services_summary': {
                    'total_services': len(pricing_entries),
                    'available_services_count': len([e for e in pricing_entries if e.get('price', 0) > 0]),
                    'not_available_services_count': len([e for e in pricing_entries if e.get('price', 0) == 0])
                },
                'created_at': datetime.datetime.now().isoformat(),
                'updated_at': datetime.datetime.now().isoformat()
            }

            file_content = json.dumps(pricing_data, indent=4)
            file_key = f"vendor_register_details/{sanitize_email(vendor_email)}/pricing.json"

            s3.put_object(Bucket=settings.R2_BUCKET,
                          Key=file_key,
                          Body=file_content,
                          ContentType='application/json')

            print(f"✅ Successfully saved pricing data for vendor {vendor_email}")

            return JsonResponse({
                'success': True,
                'message': 'Pricing saved successfully',
                'total_services': pricing_data['services_summary']['total_services'],
                'available_services_count': pricing_data['services_summary']['available_services_count'],
                'not_available_services_count': pricing_data['services_summary']['not_available_services_count'],
                'categorized_pricing': categorized_pricing
            })

        except Exception as e:
            print(f"❌ Error saving pricing data: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Error saving pricing: {str(e)}'
            })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })


def vendor_info(request, vendor_id):
    """
    Get vendor information by vendor ID
    """
    try:
        # Initialize S3 client
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Look for vendor registration file
        file_key = f"vendor_register_details/{sanitize_email(vendor_id)}/registration_details.json"

        try:
            response = s3.get_object(Bucket=settings.R2_BUCKET, Key=file_key)
            vendor_data = json.loads(response['Body'].read().decode('utf-8'))

            return JsonResponse({
                'success': True,
                'vendor': {
                    'vendor_id': vendor_id,
                    'vendor_name': vendor_data.get('vendor_name', ''),
                    'email': vendor_data.get('email', ''),
                    'phone_number': vendor_data.get('phone_number', '')
                }
            })

        except s3.exceptions.NoSuchKey:
            return JsonResponse({
                'success': False,
                'message': 'Vendor not found'
            })

    except Exception as e:
        print(f"❌ Error fetching vendor info: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Error fetching vendor info: {str(e)}'
        })


# Add vendor login endpoint
@csrf_exempt
def vendor_login(request):
    """
    Handle vendor login by email using new R2 storage structure
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')  # frontend now sends email as 'email'
            password = data.get('password')

            if not email or not password:
                return JsonResponse({
                    'success': False,
                    'message': 'Email and password are required'
                })

            # Initialize R2 client
            s3 = boto3.client('s3',
                              aws_access_key_id=settings.R2_ACCESS_KEY,
                              aws_secret_access_key=settings.R2_SECRET_KEY,
                              endpoint_url=settings.R2_ENDPOINT,
                              region_name='auto')

            # Search for vendor by email in the new R2 structure
            found_vendor = None
            vendor_id = None

            try:
                # First, try to get vendor registration details directly
                reg_key = f'vendor_register_details/{sanitize_email(email)}/registration_details.json'
                try:
                    reg_response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
                    reg_details = json.loads(reg_response['Body'].read().decode('utf-8'))
                    vendor_id = reg_details.get('vendor_id')
                    print(f"🔍 Found vendor ID from registration details: {vendor_id}")
                except Exception as e:
                    print(f"Could not get registration details: {str(e)}")
                
                # Get login details
                login_key = f'vendor_register_details/{sanitize_email(email)}/login_details.json'
                try:
                    login_response = s3.get_object(Bucket=settings.R2_BUCKET, Key=login_key)
                    found_vendor = json.loads(login_response['Body'].read().decode('utf-8'))
                    print(f"🔍 Found login details for: {email}")
                except Exception as e:
                    print(f"Could not get login details: {str(e)}")
                    # Fallback: search through all login details
                    objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
                    for obj in objects.get("Contents", []):
                        if obj["Key"].endswith('/login_details.json'):
                            try:
                                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                                login_details = json.loads(response['Body'].read().decode('utf-8'))
                                if login_details.get('email') == email:
                                    found_vendor = login_details
                                    break
                            except Exception as e:
                                print(f"Error reading login details from {obj['Key']}: {str(e)}")
                                continue

                if not found_vendor:
                    return JsonResponse({
                        'success': False,
                        'message': 'Vendor not found with this email address'
                    })

                # Check password
                if check_password(password, found_vendor['hashed_password']):
                    # Update last login timestamp
                    found_vendor['last_login'] = timezone.now().isoformat()
                    login_key = f'vendor_register_details/{sanitize_email(email)}/login_details.json'
                    s3.put_object(Bucket=settings.R2_BUCKET, Key=login_key, Body=json.dumps(found_vendor), ContentType='application/json')

                    # Get vendor registration details for additional info
                    try:
                        reg_response = s3.get_object(Bucket=settings.R2_BUCKET, Key=f'vendor_register_details/{sanitize_email(email)}/registration_details.json')
                        reg_details = json.loads(reg_response['Body'].read().decode('utf-8'))
                        vendor_name = reg_details.get('vendor_name', '')
                        vendor_id = reg_details.get('vendor_id', vendor_id)  # Use vendor_id from registration details
                        print(f"✅ Retrieved vendor details - Name: {vendor_name}, ID: {vendor_id}")
                    except Exception as e:
                        vendor_name = ''
                        vendor_id = vendor_id  # Keep the extracted vendor_id
                        print(f"⚠️ Could not get registration details: {str(e)}")
                    
                    # Set vendor email and vendor_id in session
                    request.session['vendor_email'] = email
                    request.session['vendor_id'] = vendor_id
                    
                    print(f"✅ Vendor login successful: {email} (ID: {vendor_id})")
                    
                    return JsonResponse({
                        'success': True,
                        'message': 'Login successful',
                        'vendor': {
                            'vendor_id': vendor_id,
                            'vendor_name': vendor_name,
                            'email': email
                        }
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid password'
                    })

            except Exception as e:
                print(f"Error searching for vendor: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'message': 'Error finding vendor account'
                })

        except Exception as e:
            print(f"Error during vendor login: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Login error: {str(e)}'
            })

    return JsonResponse({
        'success': False,
        'message': 'Invalid request method'
    })


# Add vendor registration endpoint
@csrf_exempt
def vendor_register_api(request):
    """
    Handle vendor registration API
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            password = data.get('password')
            vendor_name = data.get('vendor_name')
            phone_number = data.get('phone_number')
            shop_address = data.get('shop_address')
            city = data.get('city')
            pincode = data.get('pincode')
            latitude = data.get('latitude')
            longitude = data.get('longitude')

            # Validate required fields
            if not all([email, password, vendor_name, phone_number, shop_address, city, pincode]):
                return JsonResponse({
                    'success': False,
                    'message': 'All fields are required'
                })

            # Validate email format
            email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
            if not re.match(email_regex, email):
                return JsonResponse({
                    'success': False,
                    'message': 'Please enter a valid email address'
                })

            # Validate password strength
            if len(password) < 8:
                return JsonResponse({
                    'success': False,
                    'message': 'Password must be at least 8 characters long'
                })

            if not re.search(r'[a-zA-Z]', password) or not re.search(r'\d', password):
                return JsonResponse({
                    'success': False,
                    'message': 'Password must contain at least one letter and one number'
                })

            # Validate phone number (10 digits)
            phone_clean = re.sub(r'\D', '', phone_number)
            if len(phone_clean) != 10:
                return JsonResponse({
                    'success': False,
                    'message': 'Please enter a valid 10-digit phone number'
                })

            # Generate unique 10-digit vendor ID and token
            vendor_id = str(random.randint(1000000000, 9999999999))
            vendor_token = str(random.randint(1000000000, 9999999999))

            # Hash password
            password_hash = make_password(password)

            # Initialize S3 client
            s3 = boto3.client('s3',
                              aws_access_key_id=settings.R2_ACCESS_KEY,
                              aws_secret_access_key=settings.R2_SECRET_KEY,
                              endpoint_url=settings.R2_ENDPOINT,
                              region_name='auto')

            # Check if email already exists
            try:
                objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=f'vendor_register_details/{sanitize_email(email)}/')
                for obj in objects.get("Contents", []):
                    if obj["Key"].endswith('registration_details.json'):
                        return JsonResponse({
                            'success': False,
                            'message': 'Email already registered'
                        })
            except Exception as e:
                print(f"Warning: Could not check for existing email: {str(e)}")

            # Prepare registration details
            registration_details = {
                'vendor_email': email,
                'vendor_name': vendor_name,
                'vendor_id': vendor_id,
                'vendor_token': vendor_token,
                'phone_number': phone_number,
                'shop_address': shop_address,
                'city': city,
                'pincode': pincode,
                'latitude': latitude,
                'longitude': longitude,
                'registration_date': timezone.now().isoformat(),
                'hashed_password': password_hash
            }
            reg_key = f'vendor_register_details/{sanitize_email(email)}/registration_details.json'
            s3.put_object(Bucket=settings.R2_BUCKET, Key=reg_key, Body=json.dumps(registration_details), ContentType='application/json')

            # Prepare login details
            login_details = {
                'email': email,
                'hashed_password': password_hash,
                'last_login': None
            }
            login_key = f'vendor_register_details/{sanitize_email(email)}/login_details.json'
            s3.put_object(Bucket=settings.R2_BUCKET, Key=login_key, Body=json.dumps(login_details), ContentType='application/json')

            # Create shop folder with vendor name
            shop_folder_name = sanitize_shop_name(vendor_name)
            shop_folder_key = f'vendor_register_details/{sanitize_email(email)}/{shop_folder_name}/'

            # Create shop info file with hashed vendor ID and token
            s3.put_object(
                Bucket=settings.R2_BUCKET,
                Key=f'{shop_folder_key}shop_info.json',
                Body=json.dumps({
                    'shop_name': vendor_name,
                    'vendor_id_hash': make_password(vendor_id),
                    'vendor_token_hash': make_password(vendor_token),
                    'created_at': timezone.now().isoformat(),
                    'folder_created': True
                }),
                ContentType='application/json'
            )

            # Prepare pricing details if present
            pricing_entries = data.get('pricing_entries', [])
            for entry in pricing_entries:
                pricing_id = str(uuid.uuid4())
                key = f'vendor_register_details/{sanitize_email(email)}/pricing_details/pricing_{pricing_id}.json'
                s3.put_object(Bucket=settings.R2_BUCKET, Key=key, Body=json.dumps(entry), ContentType='application/json')

            print(f"✅ Successfully registered vendor {email} with shop folder: {shop_folder_name}")
            
            # Send welcome email
            try:
                send_welcome_email(email, vendor_name)
            except Exception as e:
                print(f"⚠️ Warning: Could not send welcome email to {email}: {str(e)}")

            return JsonResponse({
                'success': True,
                'message': 'Registration successful',
                'vendor_email': email,
                'vendor_id': vendor_id,
                'vendor_token': vendor_token,
                'shop_folder': shop_folder_name
            })

        except Exception as e:
            print(f"❌ Error during vendor registration: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Registration error: {str(e)}'
            })

    return JsonResponse({
        'success': False,
        'message': 'Invalid request method'
    })

@csrf_exempt
def vendor_authenticate(request):
    """
    Authenticate vendor using vendor_id and vendor_token (hashed in shop_info.json)
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            vendor_email = data.get('vendor_email')
            vendor_id = data.get('vendor_id')
            vendor_token = data.get('vendor_token')
            shop_name = data.get('shop_name')

            if not all([vendor_email, vendor_id, vendor_token, shop_name]):
                return JsonResponse({'success': False, 'error': 'Missing credentials'}, status=400)

            s3 = boto3.client('s3',
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                endpoint_url=settings.R2_ENDPOINT,
                region_name='auto'
            )
            shop_folder = sanitize_shop_name(shop_name)
            shop_info_key = f'vendor_register_details/{sanitize_email(vendor_email)}/{shop_folder}/shop_info.json'
            try:
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=shop_info_key)
                shop_info = json.loads(response['Body'].read().decode('utf-8'))
                vendor_id_hash = shop_info.get('vendor_id_hash')
                vendor_token_hash = shop_info.get('vendor_token_hash')
                if check_password(vendor_id, vendor_id_hash) and check_password(vendor_token, vendor_token_hash):
                    return JsonResponse({'success': True, 'message': 'Authenticated'})
                else:
                    return JsonResponse({'success': False, 'error': 'Invalid credentials'}, status=401)
            except Exception as e:
                return JsonResponse({'success': False, 'error': f'Shop info not found: {str(e)}'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

def sanitize_email(email):
    # Lowercase, replace @ with _at_, . with _dot_, and remove other special chars
    return re.sub(r'[^a-zA-Z0-9_]', '', email.lower().replace('@', '_at_').replace('.', '_dot_'))

def sanitize_shop_name(shop_name):
    # Convert to lowercase, replace spaces with underscores, remove special chars except underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_\s]', '', shop_name.lower())
    sanitized = re.sub(r'\s+', '_', sanitized.strip())
    return sanitized

@csrf_exempt
def get_vendor_pricing(request):
    """
    Get vendor pricing data from R2 storage
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            vendor_email = data.get('vendor_email')
            
            if not vendor_email:
                return JsonResponse({'success': False, 'error': 'Vendor email required'})

            s3 = boto3.client('s3',
                              aws_access_key_id=settings.R2_ACCESS_KEY,
                              aws_secret_access_key=settings.R2_SECRET_KEY,
                              endpoint_url=settings.R2_ENDPOINT,
                              region_name='auto')

            try:
                # Get vendor pricing file
                pricing_key = f'vendor_register_details/{sanitize_email(vendor_email)}/pricing.json'
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=pricing_key)
                pricing_data = json.loads(response['Body'].read().decode('utf-8'))
                
                # Return both old format (for backward compatibility) and new categorized format
                return JsonResponse({
                    'success': True,
                    'pricing': pricing_data.get('pricing_data', {}),
                    'categorized_pricing': pricing_data.get('categorized_pricing', {}),
                    'services_summary': pricing_data.get('services_summary', {})
                })
                
            except Exception as e:
                print(f"Error fetching pricing for {vendor_email}: {str(e)}")
                # Return default pricing if vendor pricing not found
                default_pricing = {
                    'digital_print_a4_single_bw': 2,
                    'digital_print_a4_single_color': 5,
                    'digital_print_a3_single_bw': 4,
                    'digital_print_a3_single_color': 8,
                    'gloss_print_a3_color': 12,
                    'gloss_print_a2_color': 18,
                    'gloss_print_a1_color': 24,
                    'gloss_print_a0_color': 30,
                    'jumbo_print_a3_single_bw': 6,
                    'jumbo_print_a3_single_color': 12,
                    'jumbo_print_a2_single_bw': 12,
                    'jumbo_print_a2_single_color': 18,
                    'jumbo_print_a1_single_bw': 18,
                    'jumbo_print_a1_single_color': 24,
                    'jumbo_print_a0_single_bw': 25,
                    'jumbo_print_a0_single_color': 30,
                    'photo_print_4_6_standard': 5,
                    'photo_print_5_7_standard': 8,
                    'photo_print_6_8_standard': 12,
                    'photo_print_a4_standard': 15,
                    'passport_photo_8_photos': 40,
                    'passport_photo_16_photos': 70,
                    'passport_photo_30_photos': 120,
                    'golden_embossing_per_book': 50,
                    'digital_print_quality_upgrade': 1,
                    'golden_emboss_quality_upgrade': 3
                }
                
                # Create categorized default pricing
                default_categorized = {
                    'digital_print': {
                        'digital_print_a4_single_bw': 2,
                        'digital_print_a4_single_color': 5,
                        'digital_print_a3_single_bw': 4,
                        'digital_print_a3_single_color': 8,
                        'digital_print_quality_upgrade': 1
                    },
                    'gloss_print': {
                        'gloss_print_a3_color': 12,
                        'gloss_print_a2_color': 18,
                        'gloss_print_a1_color': 24,
                        'gloss_print_a0_color': 30
                    },
                    'jumbo_print': {
                        'jumbo_print_a3_single_bw': 6,
                        'jumbo_print_a3_single_color': 12,
                        'jumbo_print_a2_single_bw': 12,
                        'jumbo_print_a2_single_color': 18,
                        'jumbo_print_a1_single_bw': 18,
                        'jumbo_print_a1_single_color': 24,
                        'jumbo_print_a0_single_bw': 25,
                        'jumbo_print_a0_single_color': 30
                    },
                    'photo_print': {
                        'photo_print_4_6_standard': 5,
                        'photo_print_5_7_standard': 8,
                        'photo_print_6_8_standard': 12,
                        'photo_print_a4_standard': 15
                    },
                    'passport_photo': {
                        'passport_photo_8_photos': 40,
                        'passport_photo_16_photos': 70,
                        'passport_photo_30_photos': 120
                    },
                    'golden_embossing': {
                        'golden_embossing_per_book': 50,
                        'golden_emboss_quality_upgrade': 3
                    }
                }
                
                return JsonResponse({
                    'success': True,
                    'pricing': default_pricing,
                    'categorized_pricing': default_categorized,
                    'services_summary': {
                        'total_services': len(default_pricing),
                        'available_services_count': len(default_pricing),
                        'not_available_services_count': 0
                    }
                })
                
        except Exception as e:
            print(f"Error in get_vendor_pricing: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def get_available_shops(request):
    """
    Get all available shops from R2 storage vendor registration details
    """
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        shops = []
        try:
            objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
            for obj in objects.get("Contents", []):
                key = obj["Key"]
                if key.endswith('/registration_details.json'):
                    try:
                        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                        vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                        vendor_name = vendor_data.get('vendor_name', '')
                        vendor_email = vendor_data.get('vendor_email', '')
                        shop_address = vendor_data.get('shop_address', '')
                        city = vendor_data.get('city', '')
                        latitude = vendor_data.get('latitude', '')
                        longitude = vendor_data.get('longitude', '')
                        if vendor_name and vendor_email:
                            shop_folder = sanitize_shop_name(vendor_name)
                            shop_info = {
                                'shop_name': vendor_name,
                                'shop_folder': shop_folder,
                                'vendor_email': vendor_email,
                                'shop_address': shop_address,
                                'city': city,
                                'latitude': latitude,
                                'longitude': longitude,
                                'status': 'Available',
                                'vendor_id': vendor_data.get('vendor_id', ''),
                                'vendor_token': vendor_data.get('vendor_token', '')
                            }
                            if not any(s['shop_folder'] == shop_folder for s in shops):
                                shops.append(shop_info)
                    except Exception as e:
                        print(f"Error reading vendor data from {key}: {str(e)}")
                        continue
        except Exception as e:
            print(f"Error listing vendor folders: {str(e)}")
        return JsonResponse({
            'success': True,
            'shops': shops,
            'total_shops': len(shops)
        })
    except Exception as e:
        print(f"Error getting available shops: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'shops': []
        })

def vendor_email_folder(email):
    return f'vendor_register_details/{sanitize_email(email)}'

def get_vendor_email_by_shop_folder(shop_folder):
    """Get vendor email by shop folder name from R2 storage"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Search through vendor registration details to find matching shop folder
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
        for obj in objects.get("Contents", []):
            if obj["Key"].endswith('/registration_details.json'):
                try:
                    response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                    vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                    vendor_name = vendor_data.get('vendor_name', '')
                    vendor_email = vendor_data.get('vendor_email', '')

                    # Check if this vendor's sanitized shop name matches
                    if sanitize_shop_name(vendor_name) == shop_folder:
                        return vendor_email
                except Exception as e:
                    print(f"Error reading vendor data from {obj['Key']}: {str(e)}")
                    continue

        # Fallback for firozshop or unknown shops
        return 'firozshop@example.com'

    except Exception as e:
        print(f"Error finding vendor email for shop {shop_folder}: {str(e)}")
        return 'firozshop@example.com'

def get_vendor_id_by_shop_folder(shop_folder):
    """Get vendor_id by shop folder name from R2 storage"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Search through vendor registration details to find matching shop folder
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
        for obj in objects.get("Contents", []):
            if obj["Key"].endswith('/registration_details.json'):
                try:
                    response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                    vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                    vendor_name = vendor_data.get('vendor_name', '')
                    vendor_id = vendor_data.get('vendor_id', '')

                    # Check if this vendor's sanitized shop name matches
                    if sanitize_shop_name(vendor_name) == shop_folder:
                        return vendor_id
                except Exception as e:
                    print(f"Error reading vendor data from {obj['Key']}: {str(e)}")
                    continue

        # Fallback for firozshop or unknown shops
        return 'vendor1'

    except Exception as e:
        print(f"Error finding vendor_id for shop {shop_folder}: {str(e)}")
        return 'vendor1'

def get_vendor_email_by_vendor_id(vendor_id):
    """Get vendor email by vendor_id from R2 storage"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Search through vendor registration details to find matching vendor_id
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
        for obj in objects.get("Contents", []):
            if obj["Key"].endswith('/registration_details.json'):
                try:
                    response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                    vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                    stored_vendor_id = vendor_data.get('vendor_id', '')
                    vendor_email = vendor_data.get('vendor_email', '')

                    # Check if this vendor's ID matches
                    if stored_vendor_id == vendor_id:
                        return vendor_email
                except Exception as e:
                    print(f"Error reading vendor data from {obj['Key']}: {str(e)}")
                    continue

        # Fallback for firozshop or unknown vendors
        return 'firozshop@example.com'

    except Exception as e:
        print(f"Error finding vendor email for vendor_id {vendor_id}: {str(e)}")
        return 'firozshop@example.com'

# This code incorporates address fields into the vendor registration API and updates the pricing structure to handle comprehensive xerox shop pricing.

# --- PicWish Passport Photo Enhancement API ---
@csrf_exempt
def debug_vendor_registrations(request):
    """
    Debug endpoint to list all vendor registrations
    """
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        vendors = []
        try:
            objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
            for obj in objects.get("Contents", []):
                key = obj["Key"]
                if key.endswith('/registration_details.json'):
                    try:
                        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                        vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                        vendors.append({
                            'vendor_id': vendor_data.get('vendor_id', ''),
                            'vendor_email': vendor_data.get('vendor_email', ''),
                            'vendor_name': vendor_data.get('vendor_name', ''),
                            'latitude': vendor_data.get('latitude', ''),
                            'longitude': vendor_data.get('longitude', ''),
                            'file_path': key
                        })
                    except Exception as e:
                        print(f"Error reading vendor data from {key}: {str(e)}")
                        continue
        except Exception as e:
            print(f"Error listing vendor folders: {str(e)}")
        
        return JsonResponse({
            'success': True,
            'vendors': vendors,
            'total_vendors': len(vendors)
        })
    except Exception as e:
        print(f"Error getting vendor registrations: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'vendors': []
        })

@csrf_exempt
def enhance_passport_photo(request):
    """
    Accepts an image file, sends it to PicWish API, downloads the enhanced image, and returns it as base64.
    """
    if request.method != 'POST' or 'file' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No image uploaded.'}, status=400)

    image_file = request.FILES['file']
    api_key = 'wxvzd1pi3lnd7t015'
    url = 'https://techhk.aoscdn.com/api/tasks/visual/scale'
    headers = {'X-API-KEY': api_key}
    files = {'image_file': (image_file.name, image_file.read(), image_file.content_type)}
    data = {
        'sync': '1',  # Synchronous
        'type': 'face',  # For passport/portrait
        'scale_factor': '2',  # 2x enhancement
        'return_type': '1'  # Return image URL
    }
    try:
        response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        result = response.json()
        if result.get('status') == 200 and 'image' in result.get('data', {}):
            enhanced_url = result['data']['image']
            # Download the enhanced image immediately
            img_resp = requests.get(enhanced_url, timeout=60)
            if img_resp.status_code == 200:
                img_b64 = base64.b64encode(img_resp.content).decode('utf-8')
                return JsonResponse({'success': True, 'enhanced_image_b64': img_b64})
            else:
                return JsonResponse({'success': False, 'error': 'Failed to download enhanced image.'}, status=500)
        else:
            return JsonResponse({'success': False, 'error': result.get('error', 'Enhancement failed.')}, status=500)
    except Exception as e:

        return JsonResponse({'success': False, 'error': str(e)}, status=500)

       


# ─────────────────────────────────────────────────────────────
# FILE UPLOAD TO CLOUDFLARE R2
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# FORGOT PASSWORD SERVICE
# ─────────────────────────────────────────────────────────────

def forgot_password_page(request):
    """Render the forgot password page"""
    return render(request, 'forgot_password.html')

@csrf_exempt
def forgot_password(request):
    """
    Send verification code to vendor email for password reset
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            
            if not email:
                return JsonResponse({'success': False, 'error': 'Email is required'})
            
            s3 = boto3.client('s3',
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                endpoint_url=settings.R2_ENDPOINT,
                region_name='auto'
            )
            
            # Check if vendor exists
            reg_key = f'vendor_register_details/{sanitize_email(email)}/registration_details.json'
            try:
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
                vendor_data = json.loads(response['Body'].read().decode('utf-8'))
            except Exception as e:
                return JsonResponse({'success': False, 'error': 'Vendor not found with this email'})
            
            # Generate 6-digit verification code
            verification_code = str(random.randint(100000, 999999))
            
            # Store verification code with expiration (15 minutes)
            reset_data = {
                'email': email,
                'code': verification_code,
                'created_at': datetime.datetime.now().isoformat(),
                'expires_at': (datetime.datetime.now() + datetime.timedelta(minutes=15)).isoformat(),
                'used': False
            }
            
            reset_key = f'password_reset/{sanitize_email(email)}/reset_data.json'
            s3.put_object(
                Bucket=settings.R2_BUCKET,
                Key=reset_key,
                Body=json.dumps(reset_data),
                ContentType='application/json'
            )
            
            # Send email with verification code
            vendor_name = vendor_data.get('vendor_name', 'Vendor')
            email_sent = send_password_reset_email(email, verification_code, vendor_name)
            
            if email_sent:
                return JsonResponse({
                    'success': True,
                    'message': 'Verification code sent to your email'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to send verification email. Please try again.'
                })
            
        except Exception as e:
            print(f"Error in forgot_password: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Internal server error'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def verify_reset_code(request):
    """
    Verify the reset code sent to vendor email
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            code = data.get('code')
            
            if not email or not code:
                return JsonResponse({'success': False, 'error': 'Email and code are required'})
            
            s3 = boto3.client('s3',
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                endpoint_url=settings.R2_ENDPOINT,
                region_name='auto'
            )
            
            # Get reset data
            reset_key = f'password_reset/{sanitize_email(email)}/reset_data.json'
            try:
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reset_key)
                reset_data = json.loads(response['Body'].read().decode('utf-8'))
            except Exception as e:
                return JsonResponse({'success': False, 'error': 'Invalid or expired reset code'})
            
            # Check if code is expired
            expires_at = datetime.datetime.fromisoformat(reset_data['expires_at'])
            if datetime.datetime.now() > expires_at:
                return JsonResponse({'success': False, 'error': 'Reset code has expired'})
            
            # Check if code matches
            if reset_data['code'] != code:
                return JsonResponse({'success': False, 'error': 'Invalid verification code'})
            
            # Check if already used
            if reset_data.get('used', False):
                return JsonResponse({'success': False, 'error': 'Reset code already used'})
            
            return JsonResponse({
                'success': True,
                'message': 'Code verified successfully'
            })
            
        except Exception as e:
            print(f"Error in verify_reset_code: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Internal server error'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def reset_password(request):
    """
    Reset vendor password with verification code
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            code = data.get('code')
            new_password = data.get('new_password')
            
            if not all([email, code, new_password]):
                return JsonResponse({'success': False, 'error': 'All fields are required'})
            
            if len(new_password) < 8:
                return JsonResponse({'success': False, 'error': 'Password must be at least 8 characters long'})
            
            s3 = boto3.client('s3',
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                endpoint_url=settings.R2_ENDPOINT,
                region_name='auto'
            )
            
            # Verify reset code first
            reset_key = f'password_reset/{sanitize_email(email)}/reset_data.json'
            try:
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reset_key)
                reset_data = json.loads(response['Body'].read().decode('utf-8'))
            except Exception as e:
                return JsonResponse({'success': False, 'error': 'Invalid or expired reset code'})
            
            # Check if code is expired
            expires_at = datetime.datetime.fromisoformat(reset_data['expires_at'])
            if datetime.datetime.now() > expires_at:
                return JsonResponse({'success': False, 'error': 'Reset code has expired'})
            
            # Check if code matches
            if reset_data['code'] != code:
                return JsonResponse({'success': False, 'error': 'Invalid verification code'})
            
            # Check if already used
            if reset_data.get('used', False):
                return JsonResponse({'success': False, 'error': 'Reset code already used'})
            
            # Hash the new password
            hashed_password = make_password(new_password)
            
            # Update vendor registration details
            reg_key = f'vendor_register_details/{sanitize_email(email)}/registration_details.json'
            try:
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
                vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                
                # Update password
                vendor_data['hashed_password'] = hashed_password
                vendor_data['password_updated_at'] = datetime.datetime.now().isoformat()
                
                s3.put_object(
                    Bucket=settings.R2_BUCKET,
                    Key=reg_key,
                    Body=json.dumps(vendor_data),
                    ContentType='application/json'
                )
                
                # Update login details
                login_key = f'vendor_register_details/{sanitize_email(email)}/login_details.json'
                try:
                    login_response = s3.get_object(Bucket=settings.R2_BUCKET, Key=login_key)
                    login_data = json.loads(login_response['Body'].read().decode('utf-8'))
                except:
                    login_data = {'email': email}
                
                login_data['hashed_password'] = hashed_password
                login_data['last_password_reset'] = datetime.datetime.now().isoformat()
                
                s3.put_object(
                    Bucket=settings.R2_BUCKET,
                    Key=login_key,
                    Body=json.dumps(login_data),
                    ContentType='application/json'
                )
                
                # Mark reset code as used
                reset_data['used'] = True
                reset_data['used_at'] = datetime.datetime.now().isoformat()
                s3.put_object(
                    Bucket=settings.R2_BUCKET,
                    Key=reset_key,
                    Body=json.dumps(reset_data),
                    ContentType='application/json'
                )
                
                return JsonResponse({
                    'success': True,
                    'message': 'Password reset successfully'
                })
                
            except Exception as e:
                print(f"Error updating vendor data: {str(e)}")
                return JsonResponse({'success': False, 'error': 'Failed to update password'})
            
        except Exception as e:
            print(f"Error in reset_password: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Internal server error'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


# ─────────────────────────────────────────────────────────────
# ENHANCED PHOTO SERVICE
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# EMAIL UTILITIES
# ─────────────────────────────────────────────────────────────

def send_password_reset_email(email, verification_code, vendor_name):
    """
    Send password reset verification email to vendor
    """
    try:
        subject = 'Password Reset Verification - PrintMax'
        
        # Render HTML email template
        html_message = render_to_string('emails/password_reset.html', {
            'vendor_name': vendor_name,
            'verification_code': verification_code,
            'email': email
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
        
        print(f"✅ Password reset email sent successfully to {email}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending password reset email to {email}: {str(e)}")
        return False

def send_welcome_email(email, vendor_name):
    """
    Send welcome email to new vendors
    """
    try:
        subject = 'Welcome to PrintMax - Your Vendor Account is Ready!'
        
        html_message = f"""
        <html>
        <body>
            <h2>🚀 Welcome to PrintMax, {vendor_name}!</h2>
            <p>Your vendor account has been successfully created and is ready to use.</p>
            <p>You can now:</p>
            <ul>
                <li>Login to your vendor dashboard</li>
                <li>Manage print jobs</li>
                <li>Track your earnings</li>
                <li>Update your shop information</li>
            </ul>
            <p>Thank you for choosing PrintMax!</p>
        </body>
        </html>
        """
        
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
        
        print(f"✅ Welcome email sent successfully to {email}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending welcome email to {email}: {str(e)}")
        return False


# ─────────────────────────────────────────────────────────────
# LOGOUT SERVICE
# ─────────────────────────────────────────────────────────────

def logout_view(request):
    """
    Handle logout for both users and vendors
    """
    try:
        # Clear all session data
        request.session.flush()
        
        # Clear any authentication cookies
        response = redirect('home')
        response.delete_cookie('sessionid')
        response.delete_cookie('csrftoken')
        
        print("✅ User logged out successfully")
        return response
        
    except Exception as e:
        print(f"❌ Error during logout: {str(e)}")
        # Even if there's an error, redirect to home
        return redirect('home')


# ─────────────────────────────────────────────────────────────
# FORGOT PASSWORD SERVICE
# ─────────────────────────────────────────────────────────────

def get_vendor_email_by_vendor_id(vendor_id):
    """
    Given a vendor_id, search all vendor registration details in R2 and return the corresponding email.
    """
    import boto3, json
    from django.conf import settings

    s3 = boto3.client('s3',
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_KEY,
        endpoint_url=settings.R2_ENDPOINT,
        region_name='auto'
    )

    try:
        # List all registration details
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
        for obj in objects.get("Contents", []):
            if obj["Key"].endswith('/registration_details.json'):
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                if vendor_data.get('vendor_id') == vendor_id:
                    return vendor_data.get('vendor_email')
    except Exception as e:
        print(f"Error finding vendor email for vendor_id {vendor_id}: {str(e)}")
    return None

def get_vendor_coordinates(request):
    """
    Return vendor coordinates as JSON for the map, non-blocking for dashboard load.
    """
    import boto3, json
    from django.conf import settings
    coordinates = []
    try:
        s3 = boto3.client('s3',
            aws_access_key_id=settings.R2_ACCESS_KEY,
            aws_secret_access_key=settings.R2_SECRET_KEY,
            endpoint_url=settings.R2_ENDPOINT,
            region_name='auto')
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
        for obj in objects.get("Contents", []):
            if obj["Key"].endswith('/registration_details.json'):
                try:
                    response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                    vendor_data = json.loads(response['Body'].read().decode('utf-8'))
                    lat = vendor_data.get('latitude')
                    lng = vendor_data.get('longitude')
                    if lat and lng:
                        coordinates.append({
                            'vendor_id': vendor_data.get('vendor_id'),
                            'vendor_email': vendor_data.get('vendor_email'),
                            'latitude': lat,
                            'longitude': lng,
                            'shop_name': vendor_data.get('vendor_name'),
                            'city': vendor_data.get('city')
                        })
                except Exception as e:
                    continue
        return JsonResponse({'coordinates': coordinates})
    except Exception as e:
        return JsonResponse({'coordinates': [], 'error': str(e)})

def create_job_completion_notification(user_email, filename, token, vendor_name, service_type, completion_time):
    # Stub: implement notification logic if needed
    pass

@csrf_exempt
def mark_notification_read(request):
    # Stub: Mark a notification as read (expand as needed)
    if request.method == 'POST':
        return JsonResponse({'success': True, 'message': 'Notification marked as read'})
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

@csrf_exempt
def get_user_notifications(request):
    # Stub: Return user notifications (expand as needed)
    if request.method == 'POST':
        notifications = [
            {'id': 1, 'message': 'Your print job is ready!', 'read': False}
        ]
        return JsonResponse({'success': True, 'notifications': notifications})
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

def vendor_about(request):
    return render(request, 'vendor_about.html')

def get_vendor_details(request):
    """
    API endpoint to get vendor details by email (expects 'email' as GET or POST param)
    """
    email = request.GET.get('email') or request.POST.get('email')
    if not email:
        return JsonResponse({'success': False, 'error': 'Email parameter is required'}, status=400)
    s3 = boto3.client('s3',
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_KEY,
        endpoint_url=settings.R2_ENDPOINT,
        region_name='auto'
    )
    try:
        reg_key = f'vendor_register_details/{sanitize_email(email)}/registration_details.json'
        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
        vendor_data = json.loads(response['Body'].read().decode('utf-8'))
        return JsonResponse({
            'success': True,
            'vendor_details': {
                'vendor_name': vendor_data.get('vendor_name', ''),
                'vendor_email': vendor_data.get('vendor_email', ''),
                'phone_number': vendor_data.get('phone_number', ''),
                'shop_address': vendor_data.get('shop_address', ''),
                'city': vendor_data.get('city', ''),
            }
        })
    except Exception as e:
        print(f"Error fetching vendor details for {email}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

