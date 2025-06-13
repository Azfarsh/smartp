from django.shortcuts import render

def home(request):
    return render(request, 'home.html')

def vendordashboard(request):
    return render(request, 'vendordashboard.html')

def userdashboard(request):
    return render(request,'userdashboard.html')


def get_print_requests(request):
    files = list_r2_files()
    return JsonResponse({"print_requests": files})

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import boto3

@csrf_exempt  # Only use in dev; in production use CSRF tokens properly
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

            # Optional: return public URL if accessible
            file_url = f"{settings.R2_ENDPOINT}/{settings.R2_BUCKET}/{file.name}"
            return JsonResponse({'message': 'File uploaded', 'url': file_url})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=405)

import boto3
from django.conf import settings

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

        # Dummy-style format
        file_data.append({
            "filename": key.split("/")[-1],
            "preview_url": url,
            "user": "Auto User",
            "pages": "Unknown",  # You can fetch page count using a separate parser if needed
            "status": "New",
            "uploaded_at": obj["LastModified"].strftime("%Y-%m-%d %H:%M"),
            "priority": "Medium"
        })

    return file_data
