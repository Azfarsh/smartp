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
            copies = request.POST.get("copies")
            color = request.POST.get("color")
            orientation = request.POST.get("orientation")
            
            files_uploaded = 0
            
            for key in request.FILES:
                file = request.FILES[key]
                file_content = file.read()
                
                # Create a JSON file with the same name but .json extension
                file_name = file.name
                json_file_name = f"{file_name.rsplit('.', 1)[0]}.json"
                
                # Create metadata JSON content
                metadata = {
                    "filename": file_name,
                    "copies": copies,
                    "color": color,
                    "orientation": orientation,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "status": "pending"
                }
                json_content = json.dumps(metadata)

                # Initialize S3 client
                s3 = boto3.client(
                    's3',
                    aws_access_key_id=settings.R2_ACCESS_KEY,
                    aws_secret_access_key=settings.R2_SECRET_KEY,
                    endpoint_url=settings.R2_ENDPOINT,
                    region_name='auto'
                )
                
                # Upload the original file
                s3.put_object(
                    Bucket=settings.R2_BUCKET,
                    Key=file_name,
                    Body=file_content,
                    ContentType=file.content_type
                )
                
                # Upload the metadata JSON file
                s3.put_object(
                    Bucket=settings.R2_BUCKET,
                    Key=json_file_name,
                    Body=json_content,
                    ContentType='application/json'
                )
                
                files_uploaded += 1
            
            if files_uploaded > 0:
                return JsonResponse({'success': True, 'message': f'{files_uploaded} file(s) uploaded successfully'})
            else:
                return JsonResponse({'error': 'No files uploaded'}, status=400)
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=405)


# ─────────────────────────────────────────────────────────────
# LIST OBJECTS IN CLOUDFLARE R2
# ─────────────────────────────────────────────────────────────

def list_r2_files():
    s3 = boto3.client(
        's3',
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_KEY,
        endpoint_url=settings.R2_ENDPOINT,
        region_name='auto'
    )

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
        url = s3.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': settings.R2_BUCKET, 'Key': key},
            ExpiresIn=3600
        )
        
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
                "copies": metadata.get("copies", "1"),
                "color": metadata.get("color", "bw"),
                "orientation": metadata.get("orientation", "portrait"),
                "print_options": f"{metadata.get('copies', '1')} copies, {metadata.get('color', 'bw')}, {metadata.get('orientation', 'portrait')}"
            })

        file_data.append(file_info)

    return file_data


# ─────────────────────────────────────────────────────────────
# HANDLE 'PROCEED TO PRINT' – FILE + SETTINGS
# ─────────────────────────────────────────────────────────────

@csrf_exempt
def process_print_request(request):
    if request.method == 'POST':
        try:
            copies = request.POST.get("copies")
            color = request.POST.get("color")
            orientation = request.POST.get("orientation")

            for key in request.FILES:
                file = request.FILES[key]
                file_content = file.read()
                
                # Create a JSON file with the same name but .json extension
                file_name = file.name
                json_file_name = f"{file_name.rsplit('.', 1)[0]}.json"
                
                # Create metadata JSON content
                import json
                metadata = {
                    "filename": file_name,
                    "copies": copies,
                    "color": color,
                    "orientation": orientation,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "status": "pending"
                }
                json_content = json.dumps(metadata)

                # Initialize S3 client
                s3 = boto3.client(
                    's3',
                    aws_access_key_id=settings.R2_ACCESS_KEY,
                    aws_secret_access_key=settings.R2_SECRET_KEY,
                    endpoint_url=settings.R2_ENDPOINT,
                    region_name='auto'
                )
                
                # Upload the original file
                s3.put_object(
                    Bucket=settings.R2_BUCKET,
                    Key=file_name,
                    Body=file_content,
                    ContentType=file.content_type
                )
                
                # Upload the metadata JSON file
                s3.put_object(
                    Bucket=settings.R2_BUCKET,
                    Key=json_file_name,
                    Body=json_content,
                    ContentType='application/json'
                )

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})
