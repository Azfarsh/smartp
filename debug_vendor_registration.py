#!/usr/bin/env python3
"""
Debug script for vendor registration issues
"""
import os
import sys
import django
from pathlib import Path

# Add the project directory to Python path
project_dir = Path(__file__).parent / 'smartprint'
sys.path.insert(0, str(project_dir))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartprint.settings')
django.setup()

from django.conf import settings
import boto3
import json

def check_environment():
    """Check if all required environment variables are set"""
    print("🔍 Checking environment configuration...")
    
    required_vars = [
        'R2_ACCESS_KEY',
        'R2_SECRET_KEY', 
        'R2_ENDPOINT',
        'R2_BUCKET'
    ]
    
    missing_vars = []
    for var in required_vars:
        value = getattr(settings, var, None)
        if not value:
            missing_vars.append(var)
            print(f"❌ {var}: Not set")
        else:
            print(f"✅ {var}: {'*' * min(len(str(value)), 10)}...")
    
    if missing_vars:
        print(f"\n❌ Missing environment variables: {', '.join(missing_vars)}")
        return False
    else:
        print("\n✅ All required environment variables are set")
        return True

def test_s3_connection():
    """Test S3/R2 connection"""
    print("\n🔍 Testing S3/R2 connection...")
    
    try:
        s3 = boto3.client('s3',
                         aws_access_key_id=settings.R2_ACCESS_KEY,
                         aws_secret_access_key=settings.R2_SECRET_KEY,
                         endpoint_url=settings.R2_ENDPOINT,
                         region_name='auto')
        
        # Try to list objects in the bucket
        response = s3.list_objects_v2(Bucket=settings.R2_BUCKET, MaxKeys=1)
        print("✅ S3 connection successful")
        print(f"📦 Bucket: {settings.R2_BUCKET}")
        print(f"🔗 Endpoint: {settings.R2_ENDPOINT}")
        return True
        
    except Exception as e:
        print(f"❌ S3 connection failed: {str(e)}")
        return False

def test_helper_functions():
    """Test helper functions used in registration"""
    print("\n🔍 Testing helper functions...")
    
    try:
        from print.views import sanitize_email, sanitize_shop_name
        
        # Test sanitize_email
        test_email = "test@example.com"
        sanitized_email = sanitize_email(test_email)
        print(f"✅ sanitize_email('{test_email}') = '{sanitized_email}'")
        
        # Test sanitize_shop_name
        test_shop = "Test Print Shop & Co."
        sanitized_shop = sanitize_shop_name(test_shop)
        print(f"✅ sanitize_shop_name('{test_shop}') = '{sanitized_shop}'")
        
        return True
        
    except Exception as e:
        print(f"❌ Helper functions test failed: {str(e)}")
        return False

def main():
    """Run all diagnostic tests"""
    print("🚀 Starting vendor registration diagnostics...\n")
    
    tests = [
        ("Environment Configuration", check_environment),
        ("S3/R2 Connection", test_s3_connection),
        ("Helper Functions", test_helper_functions)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"Running: {test_name}")
        print('='*50)
        
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {str(e)}")
            results.append((test_name, False))
    
    # Summary
    print(f"\n{'='*50}")
    print("DIAGNOSTIC SUMMARY")
    print('='*50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n📊 Results: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All tests passed! Vendor registration should work.")
    else:
        print("⚠️ Some tests failed. Please fix the issues above.")
    
    return passed == len(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
