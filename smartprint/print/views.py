from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import boto3
import datetime
import json

# ─────────────────────────────────────────────────────────────
# BASIC PAGE VIEWS
# ─────────────────────────────────────────────────────────────


def home(request):
    return render(request, 'home.html')


def vendordashboard(request):
    return render(request, 'vendordashboard.html')


def userdashboard(request):
    return render(request, 'userdashboard.html')


# ─────────────────────────────────────────────────────────────
# FILE LISTING FROM R2
# ─────────────────────────────────────────────────────────────


def get_print_requests(request):
    files = list_r2_files()
    return JsonResponse({"print_requests": files})


# ─────────────────────────────────────────────────────────────
# FILE UPLOAD TO CLOUDFLARE R2
# ─────────────────────────────────────────────────────────────


@csrf_exempt  # Use proper CSRF protection in production!
def upload_to_r2(request):
    if request.method == 'POST':
        # Process multiple files with their settings
        try:
            files_uploaded = 0
            file_count = int(request.POST.get('file_count', 0))

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

                    # Get the file
                    file = request.FILES[file_key]
                    file_content = file.read()

                    # Get and parse the settings JSON
                    settings_json = request.POST.get(settings_key)
                    print_settings = json.loads(settings_json)

                    # Create a JSON file with the same name but .json extension
                    file_name = file.name
                    json_file_name = f"{file_name.rsplit('.', 1)[0]}.json"

                    # Use settings from the parsed JSON
                    metadata = {
                        "filename":
                        file_name,
                        "copies":
                        str(print_settings.get("copies", "1")),
                        "color":
                        str(print_settings.get("color", "bw")),
                        "orientation":
                        str(print_settings.get("orientation", "portrait")),
                        "pageRange":
                        str(print_settings.get("pageRange", "")),
                        "specificPages":
                        str(print_settings.get("specificPages", "")),
                        "pageSize":
                        str(print_settings.get("pageSize", "A4")),
                        "spiralBinding":
                        str(print_settings.get("spiralBinding", "No")),
                        "lamination":
                        str(print_settings.get("lamination", "No")),
                        "timestamp":
                        datetime.datetime.now().isoformat(),
                        "status":
                        "pending",
                        "job_completed":
                        "NO",
                        "Trash":
                        "NO"
                    }
                    json_content = json.dumps(metadata)

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
                                      'copies': str(metadata['copies']),
                                      'color': metadata['color'],
                                      'orientation': metadata['orientation'],
                                      'pageRange': metadata['pageRange'],
                                      'specificPages': metadata['specificPages'],
                                      'pageSize': metadata['pageSize'],
                                      'spiralBinding': metadata['spiralBinding'],
                                      'lamination': metadata['lamination'],
                                      'timestamp': metadata['timestamp'],
                                      'status': metadata['status'],
                                      'job_completed': metadata['job_completed'],
                                      'trash': metadata['Trash']
                                  })

                    # Upload the JSON metadata file
                    s3.put_object(Bucket=settings.R2_BUCKET,
                                  Key=json_file_name,
                                  Body=json_content.encode('utf-8'),
                                  ContentType='application/json')

                    files_uploaded += 1

            if files_uploaded > 0:
                return JsonResponse({
                    'success':
                    True,
                    'message':
                    f'{files_uploaded} file(s) uploaded successfully'
                })
            else:
                return JsonResponse({'error': 'No files uploaded'}, status=400)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=405)


# ─────────────────────────────────────────────────────────────
# LIST OBJECTS IN CLOUDFLARE R2
# ─────────────────────────────────────────────────────────────


def list_r2_files():
    s3 = boto3.client('s3',
                      aws_access_key_id=settings.R2_ACCESS_KEY,
                      aws_secret_access_key=settings.R2_SECRET_KEY,
                      endpoint_url=settings.R2_ENDPOINT,
                      region_name='auto')

    objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET)
    file_data = []
    metadata_cache = {}

    # First pass: collect all JSON metadata files
    for obj in objects.get("Contents", []):
        key = obj["Key"]
        if key.endswith('.json'):
            try:
                response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                metadata_content = response['Body'].read().decode('utf-8')
                metadata = json.loads(metadata_content)
                # Store metadata using the original filename as key
                if 'filename' in metadata:
                    metadata_cache[metadata['filename']] = metadata
            except Exception as e:
                print(f"Error reading metadata file {key}: {str(e)}")

    # Second pass: process all non-JSON files
    for obj in objects.get("Contents", []):
        key = obj["Key"]
        # Skip JSON metadata files
        if key.endswith('.json'):
            continue

        filename = key.split("/")[-1]
        url = s3.generate_presigned_url(ClientMethod='get_object',
                                        Params={
                                            'Bucket': settings.R2_BUCKET,
                                            'Key': key
                                        },
                                        ExpiresIn=3600)

        # Default values
        file_info = {
            "filename": filename,
            "preview_url": url,
            "user": "Auto User",
            "pages": "Unknown",
            "status": "New",
            "uploaded_at": obj["LastModified"].strftime("%Y-%m-%d %H:%M"),
            "priority": "Medium"
        }

        # Add metadata if available
        if filename in metadata_cache:
            metadata = metadata_cache[filename]
            file_info.update({
                "copies":
                metadata.get("copies", "1"),
                "color":
                metadata.get("color", "bw"),
                "orientation":
                metadata.get("orientation", "portrait"),
                "print_options":
                f"{metadata.get('copies', '1')} copies, {metadata.get('color', 'bw')}, {metadata.get('orientation', 'portrait')}"
            })

        file_data.append(file_info)

    return file_data


# ─────────────────────────────────────────────────────────────
# HANDLE 'PROCEED TO PRINT' – FILE + SETTINGS
# ─────────────────────────────────────────────


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

                    # Create a JSON file with the same name but .json extension
                    file_name = file.name
                    json_file_name = f"{file_name.rsplit('.', 1)[0]}.json"

                    # Use settings from the parsed JSON
                    metadata = {
                        "filename":
                        file_name,
                        "copies":
                        str(print_settings.get("copies", "1")),
                        "color":
                        str(print_settings.get("color", "bw")),
                        "orientation":
                        str(print_settings.get("orientation", "portrait")),
                        "pageRange":
                        str(print_settings.get("pageRange", "")),
                        "specificPages":
                        str(print_settings.get("specificPages", "")),
                        "pageSize":
                        str(print_settings.get("pageSize", "A4")),
                        "spiralBinding":
                        str(print_settings.get("spiralBinding", "No")),
                        "lamination":
                        str(print_settings.get("lamination", "No")),
                        "timestamp":
                        datetime.datetime.now().isoformat(),
                        "status":
                        "pending",
                        "job_completed":
                        "NO",
                        "Trash":
                        "NO"
                    }
                    json_content = json.dumps(metadata)

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
                                      'copies': str(metadata['copies']),
                                      'color': metadata['color'],
                                      'orientation': metadata['orientation'],
                                      'pageRange': metadata['pageRange'],
                                      'specificPages': metadata['specificPages'],
                                      'pageSize': metadata['pageSize'],
                                      'spiralBinding': metadata['spiralBinding'],
                                      'lamination': metadata['lamination'],
                                      'timestamp': metadata['timestamp'],
                                      'status': metadata['status'],
                                      'job_completed': metadata['job_completed'],
                                      'trash': metadata['Trash']
                                  })

                    # Upload the JSON metadata file
                    s3.put_object(Bucket=settings.R2_BUCKET,
                                  Key=json_file_name,
                                  Body=json_content.encode('utf-8'),
                                  ContentType='application/json')

                    files_processed += 1

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


def login_page(request):
    return render(request, 'login.html')