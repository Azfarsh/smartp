#!/usr/bin/env python
"""
Script to generate vendor reports for testing
Run this script to generate historical reports for all vendors
"""

import os
import sys
import django
from pathlib import Path
import datetime
import pytz

# Add the project directory to Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartprint.settings')
django.setup()

from print.admin_views import generate_comprehensive_reports

def generate_test_reports():
    """Generate comprehensive reports for all vendors"""
    try:
        print("🔄 Starting comprehensive vendor report generation...")
        
        # Generate comprehensive reports
        generate_comprehensive_reports()
        
        print("✅ Comprehensive report generation completed!")
        
    except Exception as e:
        print(f"❌ Error generating comprehensive reports: {str(e)}")

if __name__ == "__main__":
    generate_test_reports()
