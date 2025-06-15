from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import boto3
import datetime
import json
import subprocess
import os
import tempfile

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
        file = request.FILES.get('file')
        if not file:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        try:
            s3 = boto3.client(
                's3',
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                endpoint_url=settings.R2_ENDPOINT,
                region_name='auto'
            )

            s3.put_object(
                Bucket=settings.R2_BUCKET,
                Key=file.name,
                Body=file.read(),
                ContentType=file.content_type
            )

            file_url = f"{settings.R2_ENDPOINT}/{settings.R2_BUCKET}/{file.name}"
            return JsonResponse({'message': 'File uploaded', 'url': file_url})
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

    for obj in objects.get("Contents", []):
        key = obj["Key"]
        url = s3.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': settings.R2_BUCKET, 'Key': key},
            ExpiresIn=3600
        )

        file_data.append({
            "filename": key.split("/")[-1],
            "preview_url": url,
            "user": "Auto User",
            "pages": "Unknown",
            "status": "New",
            "uploaded_at": obj["LastModified"].strftime("%Y-%m-%d %H:%M"),
            "priority": "Medium"
        })

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


# ─────────────────────────────────────────────────────────────
# AUTO PRINT DOCUMENTS
# ─────────────────────────────────────────────────────────────

@csrf_exempt
def auto_print_documents(request):
    if request.method == 'POST':
        try:
            # Get files from R2 storage
            files = list_r2_files()
            if not files:
                return JsonResponse({'message': 'No documents found for printing'})

            # Initialize R2 client
            s3 = boto3.client(
                's3',
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                endpoint_url=settings.R2_ENDPOINT,
                region_name='auto'
            )

            printed_files = []
            for file_data in files:
                try:
                    # Create a temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_data['filename'])[1]) as temp_file:
                        # Download file from R2
                        s3.download_fileobj(settings.R2_BUCKET, file_data['filename'], temp_file)
                        temp_file_path = temp_file.name

                    # Print the file using the system's default printer
                    if os.name == 'nt':  # Windows
                        os.startfile(temp_file_path, 'print')
                    else:  # Linux/Mac
                        subprocess.run(['lpr', temp_file_path])

                    printed_files.append(file_data['filename'])
                    
                    # Clean up temporary file
                    os.unlink(temp_file_path)

                except Exception as e:
                    print(f"Error printing {file_data['filename']}: {str(e)}")
                    continue

            return JsonResponse({
                'message': f'Successfully printed {len(printed_files)} documents',
                'printed_files': printed_files
            })

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=405)
