#!/usr/bin/env python3
"""
Test script to verify regular print service stores data correctly
This simulates a regular print upload and checks if it stores in database
"""

import sys
import os
import json
import uuid
from datetime import datetime

# Add the smartprint directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'smartprint'))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartprint.settings')

try:
    import django
    django.setup()
    from django.conf import settings
    from print.views import store_vendor_print_job_in_db, store_user_print_job_in_db
    
    print("=" * 60)
    print("Testing Regular Print Service Storage")
    print("=" * 60)
    print()
    
    # Test data for regular print
    test_vendor_id = "2320238093"  # From your vendor dashboard
    test_vendor_email = "azfarshaikh7860@gmail.com"  # From your vendor dashboard
    test_user_email = "azfarshaikh7860@gmail.com"  # Test user email
    test_filename = f"test_regular_print_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    # Create test metadata (same structure as regular print modal sends)
    test_metadata = {
        'copies': '1',
        'color': 'Black and White',
        'orientation': 'portrait',
        'pageRange': 'all',
        'specificPages': '',
        'pageSize': 'A4',
        'spiralBinding': 'No',
        'lamination': 'No',
        'timestamp': datetime.now().isoformat(),
        'status': 'pending',
        'job_completed': 'NO',
        'vendor_status': 'not sended',
        'trash': 'NO',
        'user': test_user_email,
        'vendor_id': test_vendor_id,
        'vendor_email': test_vendor_email,
        'job_id': str(uuid.uuid4()),
        'service_type': 'regular_print',  # Normalized service type
        'service_name': 'Regular Print',
        'token': '999',  # Test token
        'points_applied': 'false',
        'points_used': '0',
        'final_amount': '10.00'
    }
    
    # Test pricing details
    test_pricing_details = {
        'total_price': 10.00,
        'pricing_breakdown': {
            'page_count': 1,
            'num_copies': 1,
            'price_per_page': 10.00
        },
        'platform_profit': 1.50,
        'base_price': 10.00
    }
    
    storage_folder = 'vendor_print_jobs'
    vendor_r2_path = f'{storage_folder}/{test_vendor_id}/{test_filename}'
    user_r2_path = f'users/{test_user_email}/{test_filename}'
    
    print(f"📋 Test Data:")
    print(f"   Service Type: regular_print")
    print(f"   Filename: {test_filename}")
    print(f"   Vendor: {test_vendor_email}")
    print(f"   User: {test_user_email}")
    print(f"   R2 Path (Vendor): {vendor_r2_path}")
    print(f"   R2 Path (User): {user_r2_path}")
    print()
    
    # Test 1: Store vendor print job
    print("🧪 Test 1: Storing vendor print job...")
    try:
        vendor_result = store_vendor_print_job_in_db(
            vendor_id=test_vendor_id,
            vendor_email=test_vendor_email,
            user_email=test_user_email,
            filename=test_filename,
            storage_folder=storage_folder,
            r2_path=vendor_r2_path,
            metadata=test_metadata,
            pricing_details=test_pricing_details,
            user_id=None,
            shop_id=test_vendor_id
        )
        
        if vendor_result:
            print("   ✅ Vendor print job stored successfully!")
        else:
            print("   ❌ Failed to store vendor print job")
    except Exception as e:
        print(f"   ❌ Error storing vendor print job: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # Test 2: Store user print job
    print("🧪 Test 2: Storing user print job...")
    try:
        user_metadata = dict(test_metadata)
        user_metadata['storage_folder'] = 'users'
        
        user_result = store_user_print_job_in_db(
            vendor_id=test_vendor_id,
            vendor_email=test_vendor_email,
            user_email=test_user_email,
            filename=test_filename,
            storage_folder='users',
            r2_path=user_r2_path,
            metadata=user_metadata,
            pricing_details=test_pricing_details,
            user_id=None,
            shop_id=test_vendor_id
        )
        
        if user_result:
            print("   ✅ User print job stored successfully!")
        else:
            print("   ❌ Failed to store user print job")
    except Exception as e:
        print(f"   ❌ Error storing user print job: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 60)
    print("Test Complete!")
    print("=" * 60)
    print()
    print("💡 Check your database to verify the test data was stored:")
    print(f"   - Look for filename: {test_filename}")
    print(f"   - Service type should be: regular_print")
    print(f"   - Check both User_print_jobs and Vendor_print_jobs tables")
    print()
    
except ImportError as e:
    print(f"❌ Error importing Django: {str(e)}")
    print("Make sure you're running this from the correct directory")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
