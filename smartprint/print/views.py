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

# ─────────────────────────────────────────────────────────────
# BASIC PAGE VIEWS
# ─────────────────────────────────────────────────────────────


def home(request):
    return render(request, 'home.html')


def vendordashboard(request):
    try:
        files = list_r2_files()
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
                if service_type == 'regular print':
                    print_requests.append(job)
                elif service_type in manual_services:
                    manual_print_jobs.append(job)
            elif job_completed == 'YES':
                completed_jobs.append(job)
        context = {
            'manual_print_jobs': manual_print_jobs,
            'print_requests': print_requests,
            'completed_jobs': completed_jobs,
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
                    "token": metadata.get('token', '')
                }

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
        files = list_r2_files()
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
                                'vendor_id': vendor_id
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
            import traceback
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

        # Check vendor-specific folder for documents in vendor bucket
        try:
            vendor_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=vendor_folder_path)

            for obj in vendor_objects.get("Contents", []):
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
                                'token': metadata.get('token', '')
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

        # Only check vendor print jobs folders for documents
        try:
            vendor_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_print_jobs/')

            for obj in vendor_objects.get("Contents", []):
                key = obj["Key"]
                filename = key.split("/")[-1]

                # Skip folder itself and metadata files
                if not filename or filename.lower().endswith('.json'):
                    continue

                # Only process files that are in vendor_print_jobs folders
                path_parts = key.split('/')
                # Expected structure: vendor_print_jobs/{vendor_id}/{filename}
                if len(path_parts) >= 3 and path_parts[0] == 'vendor_print_jobs':
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
                                    'vendor_id': vendor_id
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
        return False


def update_file_job_status(filename, status='YES', vendor_id=None, completion_time=None):
    """
    Update the job_completed metadata for a specific file
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=settings.R2_ACCESS_KEY,
                      aws_secret_access_key=settings.R2_SECRET_KEY,
                      endpoint_url=settings.R2_ENDPOINT,
                      region_name='auto')

    try:
        # Get current object metadata
        head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=filename)
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
        else:
            current_metadata['status'] = current_metadata.get('status', 'pending')

        # Copy object with updated metadata
        copy_source = {'Bucket': settings.R2_BUCKET, 'Key': filename}

        s3.copy_object(
            CopySource=copy_source,
            Bucket=settings.R2_BUCKET,
            Key=filename,
            Metadata=current_metadata,
            MetadataDirective='REPLACE'
        )

        return True

    except Exception as e:
        print(f"Error updating job status for {filename}: {str(e)}")
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
                        'token': token
                    }

                    # Store all files in vendor_print_jobs/<vendor_id>/<filename>
                    vendor_file_key = f'vendor_print_jobs/{vendor_id}/{file.name}'
                    user_file_key = f'users/{user_email}/{file.name}'

                    # Upload to vendor folder (for vendor processing)
                    s3.put_object(
                        Bucket=settings.R2_BUCKET,
                        Key=vendor_file_key,
                        Body=file_content,
                        ContentType=content_type,
                        Metadata=file_metadata
                    )

                    # Upload to user folder (for user dashboard)
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
        # Get files from vendor print jobs folders
        vendor_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_print_jobs/')
        for obj in vendor_objects.get("Contents", []):
            key = obj["Key"]
            filename = key.split("/")[-1]
            # Skip .json files (metadata, not print jobs) and folders
            if filename.lower().endswith('.json') or not filename:
                continue
            # Only process files that are in vendor_print_jobs folders
            path_parts = key.split('/')
            # Expected structure: vendor_print_jobs/{vendor_id}/{filename}
            if len(path_parts) >= 3 and path_parts[0] == 'vendor_print_jobs':
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
                    # Extract vendor info from path
                    vendor_id = path_parts[1] if len(path_parts) > 1 else 'vendor1'
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
                        "vendor_id": vendor_id
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
        print(f"📋 Total jobs found: {len(file_data)} (Pending: {pending_count}, Completed: {completed_count})")
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

            # Find or create user
            user, created = User.objects.get_or_create(
                username=email,
                defaults={'email': email}
            )
            login(request, user)
            return JsonResponse({'status': 'success', 'email': email})
        return JsonResponse({'status': 'error', 'message': 'Invalid token'}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


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
        return render(request, 'vendor_pricing.html')
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

            # Prepare pricing data
            pricing_data = {
                'vendor_email': vendor_email,
                'pricing_data': data.get('pricing_data', {}),
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
                'message': 'Pricing saved successfully'
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
                objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='vendor_register_details/')
                for obj in objects.get("Contents", []):
                    if obj["Key"].endswith('/login_details.json'):
                        try:
                            response = s3.get_object(Bucket=settings.R2_BUCKET, Key=obj["Key"])
                            login_details = json.loads(response['Body'].read().decode('utf-8'))
                            if login_details.get('email') == email:
                                found_vendor = login_details
                                # Extract vendor_id from the key path
                                vendor_id = obj["Key"].split('/')[1].replace('vendor_', '')
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
                    except:
                        vendor_name = ''
                    # Set vendor email in session
                    request.session['vendor_email'] = email
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
                        if vendor_name and vendor_email:
                            shop_folder = sanitize_shop_name(vendor_name)
                            shop_info = {
                                'shop_name': vendor_name,
                                'shop_folder': shop_folder,
                                'vendor_email': vendor_email,
                                'shop_address': shop_address,
                                'city': city,
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

# This code incorporates address fields into the vendor registration API and updates the pricing structure to handle comprehensive xerox shop pricing.