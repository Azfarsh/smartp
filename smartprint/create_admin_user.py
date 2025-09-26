#!/usr/bin/env python
"""
Script to create a superuser for admin dashboard access
Run this script from the project root directory
"""

import os
import sys
import django

# Add the project directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartprint.settings')
django.setup()

from django.contrib.auth.models import User

def create_admin_user():
    """Create a superuser for admin dashboard access"""
    username = input("Enter admin username (default: admin): ").strip() or "admin"
    email = input("Enter admin email (default: admin@smartprint.com): ").strip() or "admin@smartprint.com"
    password = input("Enter admin password (default: admin123): ").strip() or "admin123"
    
    # Check if user already exists
    if User.objects.filter(username=username).exists():
        print(f"User '{username}' already exists!")
        return
    
    # Create superuser
    user = User.objects.create_superuser(
        username=username,
        email=email,
        password=password
    )
    
    print(f"✅ Superuser '{username}' created successfully!")
    print(f"   Email: {email}")
    print(f"   Password: {password}")
    print(f"\nYou can now access the admin dashboard at: http://localhost:8000/admin-dashboard/")
    print("Make sure to run: python manage.py runserver")

if __name__ == "__main__":
    create_admin_user()
