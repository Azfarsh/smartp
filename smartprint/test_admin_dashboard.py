#!/usr/bin/env python
"""
Test script for admin dashboard R2 data fetching
Run this to test if the R2 integration works properly
"""

import os
import sys
import django

# Add the project directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartprint.settings')
django.setup()

from print.admin_views import get_all_users_from_r2, calculate_overview_stats

def test_r2_data_fetching():
    """Test R2 data fetching for admin dashboard"""
    print("🔍 Testing R2 data fetching for admin dashboard...")
    print("=" * 50)
    
    try:
        # Test getting all users from R2
        print("📊 Fetching users data from R2 storage...")
        users_data = get_all_users_from_r2()
        
        if users_data:
            print(f"✅ Found {len(users_data)} users in R2 storage")
            print("\n📋 User Data Sample:")
            print("-" * 30)
            
            for i, user in enumerate(users_data[:3]):  # Show first 3 users
                print(f"User {i+1}:")
                print(f"  Email: {user['email']}")
                print(f"  Documents: {user['total_documents']}")
                print(f"  Total Cost: ₹{user['total_cost']}")
                print(f"  Platform Revenue: ₹{user['platform_revenue']}")
                print(f"  Last Activity: {user['last_activity']}")
                print(f"  Service Types: {[s['name'] for s in user['service_breakdown']]}")
                print()
            
            # Calculate overview stats
            print("📈 Calculating overview statistics...")
            overview = calculate_overview_stats(users_data)
            
            print("📊 Overview Statistics:")
            print("-" * 25)
            print(f"Total Users: {overview['total_users']}")
            print(f"Total Cost: ₹{overview['total_cost']}")
            print(f"Total Revenue: ₹{overview['total_revenue']}")
            print()
            
            print("✅ R2 data fetching test completed successfully!")
            print(f"🎯 Dashboard will display {len(users_data)} users with total revenue of ₹{overview['total_revenue']}")
            
        else:
            print("⚠️  No users found in R2 storage")
            print("💡 Make sure there are files in the 'users/' folder in your R2 bucket")
            
    except Exception as e:
        print(f"❌ Error testing R2 data fetching: {str(e)}")
        print("🔧 Please check your R2 credentials in settings.py")

if __name__ == "__main__":
    test_r2_data_fetching()
