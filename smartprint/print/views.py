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
    # Get real data from R2 storage for the dashboard
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

        # --- NEW: Fetch vendor details from R2 ---
        vendor_email = request.session.get('vendor_email') or request.GET.get('vendor_email')
        vendor_details = None
        if vendor_email:
            s3 = boto3.client('s3',
                              aws_access_key_id=settings.R2_ACCESS_KEY,
                              aws_secret_access_key=settings.R2_SECRET_KEY,
                              endpoint_url=settings.R2_ENDPOINT,
                              region_name='auto')
            try:
                reg_key = f'vendor_register_details/{sanitize_email(vendor_email)}/registration_details.json'
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
                vendor_details = json.loads(response['Body'].read().decode('utf-8'))
            except Exception as e:
                print(f"Error fetching vendor details for dashboard: {str(e)}")
                vendor_details = None

        context = {
            'manual_print_jobs': manual_print_jobs,
            'print_requests': print_requests,
            'completed_jobs': completed_jobs,
            'vendor_details': vendor_details,
        }
        return render(request, 'vendordashboard.html', context)
    except Exception as e:
        print(f"Error loading vendor dashboard data: {str(e)}")
        return render(request, 'vendordashboard.html', {
            'manual_print_jobs': [],
            'print_requests': [],
            'completed_jobs': [],
            'vendor_details': None,
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
                    "color": metadata.get('color', 'bw'),
                    "orientation": metadata.get('orientation', 'portrait'),
                    "pageRange": metadata.get('pagerange', 'all'),
                    "specificPages": metadata.get('specificpages', ''),
                    "pageSize": metadata.get('pagesize', 'A4'),
                    "spiralBinding": metadata.get('spiralbinding', 'No'),
                    "lamination": metadata.get('lamination', 'No'),
                    "job_completed": metadata.get('job_completed', 'NO'),
                    "timestamp": metadata.get('timestamp', obj["LastModified"].isoformat()),
                    "vendor": metadata.get('vendor', 'testshop'),
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
    """
    if request.method == 'POST':
        try:
            # Get all files with job_completed = 'NO'
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
    """Get pending print jobs from R2 storage with enhanced validation"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        pending_jobs = []

        # Check testshop folder for documents
        try:
            testshop_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='testshop/')

            for obj in testshop_objects.get("Contents", []):
                key = obj["Key"]
                filename = key.split("/")[-1]

                # Skip folder itself
                if not filename:
                    continue

                try:
                    # Get object metadata
                    head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                    metadata = head_response.get('Metadata', {})

                    # Check if job is pending (job_completed = 'NO') and service_type is 'regular print'
                    job_completed = metadata.get('job_completed', 'NO').upper()
                    status = metadata.get('status', 'pending').lower()
                    service_type = metadata.get('service_type', '').strip().lower()

                    if (job_completed == 'NO' or status == 'pending') and service_type == 'regular print':
                        # Generate download URL with proper R2 structure
                        download_url = f"printme/{key}"  # Add printme prefix for R2 structure validation

                        # Generate actual presigned URL for downloading
                        actual_download_url = s3.generate_presigned_url(
                            ClientMethod='get_object',
                            Params={
                                'Bucket': settings.R2_BUCKET,
                                'Key': key
                            },
                            ExpiresIn=3600
                        )

                        # Build job info with proper R2 structure
                        job_info = {
                            'filename': filename,
                            'download_url': actual_download_url,  # Use actual presigned URL for download
                            'r2_path': download_url,  # Use structured path for validation
                            'user_email': metadata.get('user', ''),
                            'metadata': {
                                'status': 'no',  # Set to 'no' for pending jobs
                                'job_completed': job_completed,
                                'copies': metadata.get('copies', '1'),
                                'color': metadata.get('color', 'bw'),
                                'orientation': metadata.get('orientation', 'portrait'),
                                'page_size': metadata.get('pagesize', 'A4'),
                                'pages': metadata.get('pages', '1'),
                                'timestamp': metadata.get('timestamp', obj["LastModified"].isoformat()),
                                'vendor': metadata.get('vendor', 'testshop'),
                                'user': metadata.get('user', 'Unknown'),
                                'service_type': metadata.get('service_type', ''),
                                'job_id': metadata.get('job_id', ''),
                                'token': metadata.get('token', '')
                            }
                        }

                        pending_jobs.append(job_info)
                        print(f"✅ Found pending REGULAR PRINT job: {filename} (status: {status}, completed: {job_completed})")

                except Exception as e:
                    print(f"Error processing testshop file {key}: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error accessing testshop folder: {str(e)}")

        # Also check users folder for pending jobs
        try:
            users_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='users/')

            for obj in users_objects.get("Contents", []):
                key = obj["Key"]
                filename = key.split("/")[-1]

                # Skip folder itself
                if not filename:
                    continue

                try:
                    # Get object metadata
                    head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                    metadata = head_response.get('Metadata', {})

                    # Check if job is pending
                    job_completed = metadata.get('job_completed', 'NO').upper()
                    status = metadata.get('status', 'pending').lower()

                    if job_completed == 'NO' or status == 'pending':
                        # Extract user email from path
                        path_parts = key.split('/')
                        user_email = path_parts[1] if len(path_parts) > 1 else ''

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
                            'user_email': user_email,
                            'metadata': {
                                'status': 'no',  # Set to 'no' for pending jobs
                                'job_completed': job_completed,
                                'copies': metadata.get('copies', '1'),
                                'color': metadata.get('color', 'bw'),
                                'orientation': metadata.get('orientation', 'portrait'),
                                'page_size': metadata.get('pagesize', 'A4'),
                                'pages': metadata.get('pages', '1'),
                                'timestamp': metadata.get('timestamp', obj["LastModified"].isoformat()),
                                'vendor': metadata.get('vendor', 'testshop'),
                                'user': user_email or metadata.get('user', 'Unknown'),
                                'service_type': metadata.get('service_type', ''),
                                'job_id': metadata.get('job_id', ''),
                                'token': metadata.get('token', '')
                            }
                        }

                        pending_jobs.append(job_info)
                        print(f"✅ Found pending user job: {filename} (status: {status}, completed: {job_completed})")

                except Exception as e:
                    print(f"Error processing user file {key}: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error accessing users folder: {str(e)}")

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

        # Update job completion status
        job_completed_status = 'YES' if status.upper() == 'YES' else 'NO'
        updated_files = []

        # Update testshop folder
        testshop_key = f"testshop/{filename}"
        try:
            # Check if file exists in testshop
            head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=testshop_key)
            current_metadata = head_response.get('Metadata', {})

            # Update metadata
            current_metadata['job_completed'] = job_completed_status
            current_metadata['completion_time'] = datetime.datetime.now().isoformat()
            current_metadata['completed_by_vendor'] = vendor_id

            if job_completed_status == 'YES':
                current_metadata['status'] = 'completed'

            # Copy object with updated metadata
            copy_source = {'Bucket': settings.R2_BUCKET, 'Key': testshop_key}
            s3.copy_object(
                CopySource=copy_source,
                Bucket=settings.R2_BUCKET,
                Key=testshop_key,
                Metadata=current_metadata,
                MetadataDirective='REPLACE'
            )

            updated_files.append(testshop_key)
            print(f"✅ Updated testshop job status: {testshop_key} -> {job_completed_status}")

        except Exception as e:
            print(f"⚠️  Testshop file {testshop_key} not found or error updating: {str(e)}")

        # Update users folder if user_email is provided
        if user_email:
            user_key = f"users/{user_email}/{filename}"
            try:
                # Check if file exists in users folder
                head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=user_key)
                current_metadata = head_response.get('Metadata', {})

                # Update metadata
                current_metadata['job_completed'] = job_completed_status
                current_metadata['completion_time'] = datetime.datetime.now().isoformat()
                current_metadata['completed_by_vendor'] = vendor_id

                if job_completed_status == 'YES':
                    current_metadata['status'] = 'completed'

                # Copy object with updated metadata
                copy_source = {'Bucket': settings.R2_BUCKET, 'Key': user_key}
                s3.copy_object(
                    CopySource=copy_source,
                    Bucket=settings.R2_BUCKET,
                    Key=user_key,
                    Metadata=current_metadata,
                    MetadataDirective='REPLACE'
                )

                updated_files.append(user_key)
                print(f"✅ Updated user job status: {user_key} -> {job_completed_status}")

            except Exception as e:
                print(f"⚠️  User file {user_key} not found or error updating: {str(e)}")

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
            selected_vendor = request.POST.get('selected_vendor', 'testshop')

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

                    # Override content type for better support
                    content_type_map = {
                        'pdf': 'application/pdf',
                        'doc': 'application/msword',
                        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'txt': 'text/plain',
                        'ppt': 'application/vnd.ms-powerpoint',
                        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                        'xls': 'application/vnd.ms-excel',
                        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        'jpg': 'image/jpeg',
                        'jpeg': 'image/jpeg',
                        'png': 'image/png',
                        'gif': 'image/gif',
                        'bmp': 'image/bmp',
                        'tiff': 'image/tiff',
                        'svg': 'image/svg+xml'
                    }

                    if file_extension in content_type_map:
                        content_type = content_type_map[file_extension]

                    # Create metadata object
                    file_metadata = {
                        'job_id': job_id,
                        'token': token,
                        'copies': str(print_settings.get("copies", "1")),
                        'color': str(print_settings.get("color", "bw")),
                        'orientation': str(print_settings.get("orientation", "portrait")),
                        'pagerange': str(print_settings.get("pageRange", "all")),
                        'specificpages': str(print_settings.get("specificPages", "")),
                        'pagesize': str(print_settings.get("pageSize", "A4")),
                        'spiralbinding': str(print_settings.get("spiralBinding", "No")),
                        'lamination': str(print_settings.get("lamination", "No")),
                        'timestamp': datetime.datetime.now().isoformat(),
                        'status': 'pending',
                        'job_completed': 'NO',
                        'trash': 'NO',
                        'user': user_email,
                        'priority': 'Medium',
                        'pages': str(estimate_pages_from_size(len(file_content), file_extension)),
                        'vendor': selected_vendor,
                        'original_filename': file.name,
                        'service_type': str(print_settings.get("service_type", "")),
                        'service_name': str(print_settings.get("service_name", ""))
                    }

                    # Add photo print specific metadata
                    service_type = print_settings.get("service_type", "")
                    if service_type == "photo_print":
                        file_metadata.update({
                            'image_mode': str(print_settings.get("image_mode", "")),
                            'layout': str(print_settings.get("layout", "")),
                            'photo_count': str(print_settings.get("photo_count", "")),
                            'printer': str(print_settings.get("printer", "")),
                            'paper_size': str(print_settings.get("paper_size", "")),
                            'quality': str(print_settings.get("quality", "")),
                            'paper_type': str(print_settings.get("paper_type", "")),
                            'fit_picture': str(print_settings.get("fit_picture", False))
                        })

                    # Handle photo print jobs with special folder structure
                    if service_type == "photo_print" and job_id:
                        # For photo print jobs, create a job-specific folder
                        vendor_file_key = f"{selected_vendor}/photo_jobs/{job_id}/{file.name}"
                        user_file_key = f"users/{user_email}/photo_jobs/{job_id}/{file.name}"
                    else:
                        # For regular jobs, use the standard structure
                        vendor_file_key = f"{selected_vendor}/{file.name}"
                        user_file_key = f"users/{user_email}/{file.name}"

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
        # Only get files from testshop folder
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix='testshop/')
        file_data = []

        # Process testshop files and get their metadata
        for obj in objects.get("Contents", []):
            key = obj["Key"]
            filename = key.split("/")[-1]

            # Skip .json files (metadata, not print jobs)
            if filename.lower().endswith('.json'):
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
                    "color": metadata.get('color', 'bw'),
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
                    "token": metadata.get('token', '')
                }

                # Create print options string
                file_info["print_options"] = f"{file_info['copies']} copies, {file_info['color']}, {file_info['orientation']}"

                file_data.append(file_info)

            except Exception as e:
                print(f"Error processing file {key}: {str(e)}")
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

def estimate_pages_from_size(size_bytes, extension):
    """Estimate page count based on file size and type"""
    if extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'svg']:
        return '1'
    elif extension == 'pdf':
        # Rough estimate: 100KB per page for PDF
        return str(max(1, size_bytes // 100000))
    elif extension in ['doc', 'docx']:
        # Rough estimate: 50KB per page for Word docs
        return str(max(1, size_bytes // 50000))
    elif extension in ['ppt', 'pptx']:
        # Rough estimate: 200KB per slide
        return str(max(1, size_bytes // 200000))
    else:
        return '1'

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
                                      'color': print_settings.get("color", "bw"),
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

            # Generate unique vendor ID
            vendor_id = str(uuid.uuid4())

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

            # Prepare pricing details if present
            pricing_entries = data.get('pricing_entries', [])
            for entry in pricing_entries:
                pricing_id = str(uuid.uuid4())
                key = f'vendor_register_details/{sanitize_email(email)}/pricing_details/pricing_{pricing_id}.json'
                s3.put_object(Bucket=settings.R2_BUCKET, Key=key, Body=json.dumps(entry), ContentType='application/json')

            print(f"✅ Successfully registered vendor {email}")

            return JsonResponse({
                'success': True,
                'message': 'Registration successful',
                'vendor_email': email
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

def sanitize_email(email):
    # Lowercase, replace @ with _at_, . with _dot_, and remove other special chars
    return re.sub(r'[^a-zA-Z0-9_]', '', email.lower().replace('@', '_at_').replace('.', '_dot_'))

def vendor_email_folder(email):
    return f'vendor_register_details/{sanitize_email(email)}'

# This code incorporates address fields into the vendor registration API and updates the pricing structure to handle comprehensive xerox shop pricing.