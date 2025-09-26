#!/usr/bin/env python
"""
Debug script to check vendor data structure in R2
"""

import os
import sys
import django
from pathlib import Path
import json

# Add the project directory to Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartprint.settings')
django.setup()

from django.conf import settings
import boto3

def debug_vendor_data():
    """Debug vendor data structure in R2"""
    try:
        print("🔍 Debugging vendor data structure in R2...")
        
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # List all vendor registration details
        reg_prefix = "vendor_register_details/"
        reg_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reg_prefix)
        
        print(f"Found {len(reg_objects.get('Contents', []))} objects in vendor_register_details/")
        
        if 'Contents' in reg_objects:
            for obj in reg_objects['Contents']:
                key = obj["Key"]
                print(f"\n📁 Checking: {key}")
                
                if key.endswith('registration_details.json'):
                    try:
                        # Get vendor registration details
                        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                        reg_data = json.loads(response['Body'].read().decode('utf-8'))
                        
                        print(f"  📄 Registration data:")
                        print(f"    - vendor_id: {reg_data.get('vendor_id')}")
                        print(f"    - vendor_name: {reg_data.get('vendor_name')}")
                        print(f"    - email: {reg_data.get('email')}")
                        print(f"    - Keys: {list(reg_data.keys())}")
                        
                    except Exception as e:
                        print(f"  ❌ Error reading {key}: {str(e)}")
                else:
                    print(f"  📄 File: {key}")
        
        # Also check the get_all_vendors_from_r2 function
        print("\n🔍 Testing get_all_vendors_from_r2 function...")
        from print.admin_views import get_all_vendors_from_r2
        vendors = get_all_vendors_from_r2()
        print(f"Found {len(vendors)} vendors from function")
        
        for i, vendor in enumerate(vendors):
            print(f"  Vendor {i+1}:")
            print(f"    - vendor_id: {vendor.get('vendor_id')}")
            print(f"    - vendor_name: {vendor.get('vendor_name')}")
            print(f"    - email: {vendor.get('email')}")
            print(f"    - Keys: {list(vendor.keys())}")
        
    except Exception as e:
        print(f"❌ Error debugging vendor data: {str(e)}")

if __name__ == "__main__":
    debug_vendor_data()
