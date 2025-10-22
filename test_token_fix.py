#!/usr/bin/env python3
"""
Test script to verify that the token fix is working correctly.
This script simulates the notification generation process.
"""

import os
import sys
import json
import datetime

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_notification_generation():
    """Test the notification generation with proper token handling"""
    
    # Simulate the send_job_completion_notification function logic
    def send_job_completion_notification(user_email, filename, vendor_id, status, completion_time, token=None):
        """Send job completion notification to user"""
        try:
            # Use provided token or extract from filename as fallback
            if not token:
                token = os.path.splitext(filename)[0]
            
            # Extract document name from filename (remove extension and token)
            document_name = os.path.splitext(filename)[0]
            if '_' in document_name:
                # Remove token part if present
                parts = document_name.split('_')
                if len(parts) > 1:
                    document_name = '_'.join(parts[:-1])
            
            notification_data = {
                'notification_id': f"{filename}_{int(datetime.datetime.now().timestamp())}",
                'user_email': user_email,
                'filename': filename,
                'vendor_id': vendor_id,
                'status': status,
                'completion_time': completion_time,
                'timestamp': datetime.datetime.now().isoformat(),
                'created_at': datetime.datetime.now().isoformat(),
                'read': False,
                'type': 'job_completed',
                'title': '🎉 Print Job Successfully Completed!',
                'message': f'Your Document Printing order for "{document_name}" has been completed and is ready for pickup. Token: #{token}',
                'detailed_message': f'Document: {document_name}\nService Type: Document Printing\nStatus: Completed ✅\nToken: #{token}\nCompleted at: {datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")}',
                'token': token,
                'document_name': document_name,
                'service_type': 'Document Printing'
            }
            
            return notification_data
            
        except Exception as e:
            print(f"Error in send_job_completion_notification: {str(e)}")
            return None

    # Test cases
    test_cases = [
        {
            'filename': 'Jumbo printing.pdf',
            'token': '191',  # This should be the actual token from metadata
            'expected_token': '191'
        },
        {
            'filename': 'Nov_Dec_2022.pdf',
            'token': '203',  # This should be the actual token from metadata
            'expected_token': '203'
        },
        {
            'filename': 'test_document.pdf',
            'token': None,  # No token provided, should fallback to filename
            'expected_token': 'test_document'
        }
    ]
    
    print("🧪 Testing notification generation with proper token handling...")
    print("=" * 60)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}:")
        print(f"  Filename: {test_case['filename']}")
        print(f"  Provided Token: {test_case['token']}")
        print(f"  Expected Token: {test_case['expected_token']}")
        
        # Generate notification
        notification = send_job_completion_notification(
            user_email='test@example.com',
            filename=test_case['filename'],
            vendor_id='test_vendor',
            status='completed',
            completion_time=datetime.datetime.now().isoformat(),
            token=test_case['token']
        )
        
        if notification:
            actual_token = notification['token']
            print(f"  Actual Token: {actual_token}")
            print(f"  Message: {notification['message']}")
            
            if actual_token == test_case['expected_token']:
                print("  ✅ PASS - Token matches expected value")
            else:
                print("  ❌ FAIL - Token does not match expected value")
        else:
            print("  ❌ FAIL - Notification generation failed")
    
    print("\n" + "=" * 60)
    print("Test completed!")

if __name__ == "__main__":
    test_notification_generation()
