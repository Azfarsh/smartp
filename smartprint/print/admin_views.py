from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.conf import settings
import boto3
import datetime
import json
import pytz
from django.utils import timezone
from django.http import HttpResponse
import os
from django.core.management import call_command
import threading
import time
from datetime import datetime as dt, timedelta
import schedule
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt


# Admin Dashboard Views
@staff_member_required
def admin_dashboard(request):
    """Main admin dashboard view - requires staff authentication"""
    return render(request, 'admin_dashboard.html')


@staff_member_required
def admin_users_data(request):
    """Get all users data for admin dashboard from R2 storage with month filtering"""
    try:
        # Get selected month from request
        selected_month = request.GET.get('month')
        if not selected_month:
            # Default to current month
            selected_month = datetime.datetime.now().strftime('%Y-%m')
        
        # Get users data from R2 storage users folder
        users_data = get_all_users_from_r2(selected_month)
        
        # Get available months for dropdown
        available_months = get_available_months()
        
        # Calculate overview statistics for selected month
        overview = calculate_overview_stats(users_data)
        
        # Calculate growth percentage if previous month data exists
        growth_percentage = 0.0
        if len(available_months) > 1:
            current_month_index = available_months.index(selected_month) if selected_month in available_months else 0
            if current_month_index < len(available_months) - 1:
                previous_month = available_months[current_month_index + 1]
                previous_month_data = get_monthly_overview(previous_month)
                growth_percentage = calculate_growth_percentage(overview, previous_month_data)
        
        # Add month info to overview
        overview['selected_month'] = selected_month
        overview['growth_percentage'] = growth_percentage
        overview['available_months'] = available_months
        
        return JsonResponse({
            'success': True,
            'users': users_data,
            'overview': overview,
            'total_count': len(users_data)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def get_monthly_overview(month):
    """Get overview data for a specific month"""
    try:
        users_data = get_all_users_from_r2(month)
        return calculate_overview_stats(users_data)
    except Exception as e:
        print(f"Error getting monthly overview for {month}: {str(e)}")
        return {'total_users': 0, 'total_cost': 0.0, 'total_revenue': 0.0}


def get_all_users_from_r2(selected_month=None):
    """Get all users data from R2 storage users folder with month filtering"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # List all objects in the users folder
        users_prefix = "users/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=users_prefix)
        
        users_data = []
        user_folders = set()
        
        if 'Contents' in objects:
            # Group files by user email
            for obj in objects['Contents']:
                key = obj["Key"]
                # Extract user email from path: users/email@domain.com/filename
                path_parts = key.split('/')
                if len(path_parts) >= 3 and path_parts[0] == 'users':
                    user_email = path_parts[1]
                    if user_email and '@' in user_email:  # Valid email format
                        user_folders.add(user_email)
        
        # Process each user folder
        for user_email in user_folders:
            user_data = process_user_data_from_r2(s3, user_email, selected_month)
            if user_data and user_data['total_documents'] > 0:  # Only include users with documents in selected month
                users_data.append(user_data)
        
        # Sort by last activity (most recent first)
        users_data.sort(key=lambda x: x['last_activity_date'] or datetime.datetime.min, reverse=True)
        
        return users_data
        
    except Exception as e:
        print(f"Error getting all users from R2: {str(e)}")
        return []


def get_available_months():
    """Get list of available months from R2 data"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        users_prefix = "users/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=users_prefix)
        
        months = set()
        
        if 'Contents' in objects:
            for obj in objects['Contents']:
                last_modified = obj.get('LastModified')
                if last_modified:
                    month_key = last_modified.strftime('%Y-%m')
                    months.add(month_key)
        
        # Sort months in descending order (most recent first)
        sorted_months = sorted(months, reverse=True)
        return sorted_months
        
    except Exception as e:
        print(f"Error getting available months: {str(e)}")
        return []


def calculate_growth_percentage(current_month_data, previous_month_data):
    """Calculate growth percentage month-over-month"""
    try:
        if not previous_month_data or previous_month_data['total_revenue'] == 0:
            return 0.0
        
        growth = ((current_month_data['total_revenue'] - previous_month_data['total_revenue']) / previous_month_data['total_revenue']) * 100
        return round(growth, 2)
        
    except Exception as e:
        print(f"Error calculating growth percentage: {str(e)}")
        return 0.0


def get_service_commission_rate(service_type):
    """Get commission rate for different service types"""
    commission_rates = {
        'regular print': 0.15,      # 15%
        'photo print': 0.20,        # 20%
        'passport photo': 0.25,     # 25%
        'jumbo print': 0.18,        # 18%
        'gloss print': 0.22,        # 22%
        'digital print': 0.16,      # 16%
        'a4 print': 0.14,           # 14%
        'golden emboss': 0.30,      # 30%
        'default': 0.15             # 15% default
    }
    return commission_rates.get(service_type.lower(), 0.15)


def process_user_data_from_r2(s3, user_email, selected_month=None):
    """Process individual user data from R2 storage with month filtering"""
    try:
        user_prefix = f"users/{user_email}/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=user_prefix)
        
        if 'Contents' not in objects:
            return None
        
        total_documents = 0
        total_cost = 0.0
        total_revenue = 0.0
        service_breakdown = {}
        last_activity = None
        monthly_data = {}
        
        for obj in objects['Contents']:
            key = obj["Key"]
            filename = key.split('/')[-1]
            
            # Skip if it's just the folder itself
            if filename == "":
                continue
            
            try:
                # Get file metadata
                head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                metadata = head_response.get('Metadata', {})
                
                # Get last modified date
                last_modified = obj.get('LastModified')
                if not last_modified:
                    continue
                
                # Filter by month if specified
                if selected_month:
                    file_month = last_modified.strftime('%Y-%m')
                    if file_month != selected_month:
                        continue
                
                # Count documents
                total_documents += 1
                
                # Get service type
                service_type = metadata.get('service_type', 'default')
                if service_type not in service_breakdown:
                    service_breakdown[service_type] = {'count': 0, 'total_cost': 0.0, 'total_revenue': 0.0}
                
                # Get pricing data
                price = 0.0
                if 'price' in metadata:
                    try:
                        price = float(metadata['price'])
                    except (ValueError, TypeError):
                        pass
                elif 'total_price' in metadata:
                    try:
                        price = float(metadata['total_price'])
                    except (ValueError, TypeError):
                        pass
                
                # Calculate revenue for this specific service type
                commission_rate = get_service_commission_rate(service_type)
                service_revenue = price * commission_rate
                
                # Update totals
                total_cost += price
                total_revenue += service_revenue
                
                # Update service breakdown
                service_breakdown[service_type]['count'] += 1
                service_breakdown[service_type]['total_cost'] += price
                service_breakdown[service_type]['total_revenue'] += service_revenue
                
                # Update last activity
                if not last_activity or last_modified > last_activity:
                    last_activity = last_modified
                
                # Track monthly data
                month_key = last_modified.strftime('%Y-%m')
                if month_key not in monthly_data:
                    monthly_data[month_key] = {
                        'documents': 0,
                        'total_cost': 0.0,
                        'total_revenue': 0.0
                    }
                monthly_data[month_key]['documents'] += 1
                monthly_data[month_key]['total_cost'] += price
                monthly_data[month_key]['total_revenue'] += service_revenue
                    
            except Exception as e:
                print(f"Error processing file {key}: {str(e)}")
                continue
        
        # Convert service breakdown to list format with detailed info
        service_breakdown_list = [
            {
                'name': service, 
                'count': data['count'],
                'total_cost': round(data['total_cost'], 2),
                'total_revenue': round(data['total_revenue'], 2),
                'commission_rate': f"{get_service_commission_rate(service) * 100:.0f}%"
            } 
            for service, data in service_breakdown.items()
        ]
        
        # Format last activity date
        if last_activity:
            last_activity_str = last_activity.strftime('%m/%d/%Y')
        else:
            last_activity_str = 'N/A'
        
        return {
            'email': user_email,
            'total_documents': total_documents,
            'service_breakdown': service_breakdown_list,
            'total_cost': round(total_cost, 2),
            'platform_revenue': round(total_revenue, 2),
            'last_activity': last_activity_str,
            'last_activity_date': last_activity,
            'monthly_data': monthly_data
        }
        
    except Exception as e:
        print(f"Error processing user data for {user_email}: {str(e)}")
        return None


def calculate_overview_stats(users_data):
    """Calculate overview statistics from users data"""
    try:
        total_users = len(users_data)
        total_cost = sum(user['total_cost'] for user in users_data)
        total_revenue = sum(user['platform_revenue'] for user in users_data)
        
        return {
            'total_users': total_users,
            'total_cost': round(total_cost, 2),
            'total_revenue': round(total_revenue, 2)
        }
        
    except Exception as e:
        print(f"Error calculating overview stats: {str(e)}")
        return {
            'total_users': 0,
            'total_cost': 0.0,
            'total_revenue': 0.0
        }


def get_user_total_payments_from_r2(user_email):
    """Get total payments for a user from R2 storage (legacy function)"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # Look for payment data in user's folder
        user_prefix = f"users/{user_email}/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=user_prefix)
        
        total_payments = 0.0
        
        if 'Contents' in objects:
            for obj in objects['Contents']:
                key = obj["Key"]
                if 'payment' in key.lower() or 'transaction' in key.lower():
                    try:
                        # Try to get payment data from metadata or file content
                        head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                        metadata = head_response.get('Metadata', {})
                        
                        # Check if payment amount is in metadata
                        if 'payment_amount' in metadata:
                            total_payments += float(metadata['payment_amount'])
                        elif 'amount' in metadata:
                            total_payments += float(metadata['amount'])
                    except Exception as e:
                        print(f"Error processing payment data for {key}: {str(e)}")
                        continue
        
        return round(total_payments, 2)
        
    except Exception as e:
        print(f"Error getting user payments from R2: {str(e)}")
        return 0.0


@staff_member_required
def admin_vendors_data(request):
    """Get all vendors data for admin dashboard from R2 storage"""
    try:
        # Get selected month from request
        selected_month = request.GET.get('month')
        if not selected_month:
            # Default to current month
            selected_month = datetime.datetime.now().strftime('%Y-%m')
        
        # Get vendors data from R2 storage
        vendors_data = get_all_vendors_from_r2(selected_month)
        
        # Get available months for dropdown
        available_months = get_available_months()
        
        # Calculate overview statistics for selected month
        overview = calculate_vendor_overview_stats(vendors_data)
        
        # Calculate growth percentage if previous month data exists
        growth_percentage = 0.0
        if len(available_months) > 1:
            current_month_index = available_months.index(selected_month) if selected_month in available_months else 0
            if current_month_index < len(available_months) - 1:
                previous_month = available_months[current_month_index + 1]
                previous_month_data = get_vendor_monthly_overview(previous_month)
                growth_percentage = calculate_growth_percentage(overview, previous_month_data)
        
        # Add month info to overview
        overview['selected_month'] = selected_month
        overview['growth_percentage'] = growth_percentage
        overview['available_months'] = available_months
        
        return JsonResponse({
            'success': True,
            'vendors': vendors_data,
            'overview': overview,
            'total_count': len(vendors_data)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def get_all_vendors_from_r2(selected_month=None):
    """Get all vendors data from R2 storage with month filtering"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # Get vendor registration details
        vendors_data = []
        
        # List all vendor registration details
        reg_prefix = "vendor_register_details/"
        reg_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reg_prefix)
        
        if 'Contents' in reg_objects:
            for obj in reg_objects['Contents']:
                key = obj["Key"]
                if key.endswith('registration_details.json'):
                    try:
                        # Get vendor registration details
                        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                        reg_data = json.loads(response['Body'].read().decode('utf-8'))
                        
                        vendor_id = reg_data.get('vendor_id')
                        vendor_name = reg_data.get('vendor_name', 'Unknown')
                        vendor_email = reg_data.get('vendor_email', '')
                        # If vendor_email is not in the data, extract from folder path
                        if not vendor_email:
                            # Extract email from folder path: vendor_register_details/email_at_domain_dot_com/
                            folder_path = key.split('/')[1]  # Get the folder name
                            vendor_email = folder_path.replace('_at_', '@').replace('_dot_', '.')
                        
                        if vendor_id:
                            # Get vendor documents data
                            vendor_docs_data = process_vendor_documents_from_r2(s3, vendor_id, selected_month)
                            if vendor_docs_data and vendor_docs_data['total_documents'] > 0:
                                vendor_docs_data.update({
                                    'vendor_id': vendor_id,
                                    'vendor_name': vendor_name,
                                    'email': vendor_email
                                })
                                vendors_data.append(vendor_docs_data)
                                
                    except Exception as e:
                        print(f"Error processing vendor registration {key}: {str(e)}")
                        continue
        
        # Sort by last activity (most recent first)
        vendors_data.sort(key=lambda x: x.get('last_activity_date') or datetime.datetime.min, reverse=True)
        
        return vendors_data
        
    except Exception as e:
        print(f"Error getting all vendors from R2: {str(e)}")
        return []


def process_vendor_documents_from_r2(s3, vendor_id, selected_month=None):
    """Process vendor documents from R2 storage with month filtering"""
    try:
        total_documents = 0
        total_cost = 0.0
        service_breakdown = {}
        last_activity = None
        
        # Check both vendor_print_jobs and vendor_manual_print_jobs folders
        folders = [f"vendor_print_jobs/{vendor_id}/", f"vendor_manual_print_jobs/{vendor_id}/"]
        
        for folder in folders:
            objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=folder)
            
            if 'Contents' in objects:
                for obj in objects['Contents']:
                    key = obj["Key"]
                    filename = key.split('/')[-1]
                    
                    # Skip if it's just the folder itself
                    if filename == "":
                        continue
                    
                    try:
                        # Get file metadata
                        head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                        metadata = head_response.get('Metadata', {})
                        
                        # Get last modified date
                        last_modified = obj.get('LastModified')
                        if not last_modified:
                            continue
                        
                        # Filter by month if specified
                        if selected_month:
                            file_month = last_modified.strftime('%Y-%m')
                            if file_month != selected_month:
                                continue
                        
                        # Count documents
                        total_documents += 1
                        
                        # Get service type
                        service_type = metadata.get('service_type', 'default')
                        if service_type not in service_breakdown:
                            service_breakdown[service_type] = {'count': 0, 'total_cost': 0.0}
                        
                        # Get pricing data
                        price = 0.0
                        if 'price' in metadata:
                            try:
                                price = float(metadata['price'])
                            except (ValueError, TypeError):
                                pass
                        elif 'total_price' in metadata:
                            try:
                                price = float(metadata['total_price'])
                            except (ValueError, TypeError):
                                pass
                        
                        # Update totals
                        total_cost += price
                        
                        # Update service breakdown
                        service_breakdown[service_type]['count'] += 1
                        service_breakdown[service_type]['total_cost'] += price
                        
                        # Update last activity
                        if not last_activity or last_modified > last_activity:
                            last_activity = last_modified
                            
                    except Exception as e:
                        print(f"Error processing vendor document {key}: {str(e)}")
                        continue
        
        # Convert service breakdown to list format
        service_breakdown_list = [
            {
                'name': service, 
                'count': data['count'],
                'total_cost': round(data['total_cost'], 2)
            } 
            for service, data in service_breakdown.items()
        ]
        
        # Format last activity date
        if last_activity:
            last_activity_str = last_activity.strftime('%m/%d/%Y')
        else:
            last_activity_str = 'N/A'
        
        return {
            'total_documents': total_documents,
            'service_breakdown': service_breakdown_list,
            'total_cost': round(total_cost, 2),
            'last_activity': last_activity_str,
            'last_activity_date': last_activity
        }
        
    except Exception as e:
        print(f"Error processing vendor documents for {vendor_id}: {str(e)}")
        return None


def calculate_vendor_overview_stats(vendors_data):
    """Calculate overview statistics from vendors data"""
    try:
        total_vendors = len(vendors_data)
        total_documents = sum(vendor['total_documents'] for vendor in vendors_data)
        total_cost = sum(vendor['total_cost'] for vendor in vendors_data)
        
        return {
            'total_vendors': total_vendors,
            'total_documents': total_documents,
            'total_cost': round(total_cost, 2)
        }
        
    except Exception as e:
        print(f"Error calculating vendor overview stats: {str(e)}")
        return {
            'total_vendors': 0,
            'total_documents': 0,
            'total_cost': 0.0
        }


def get_vendor_monthly_overview(month):
    """Get vendor overview data for a specific month"""
    try:
        vendors_data = get_all_vendors_from_r2(month)
        return calculate_vendor_overview_stats(vendors_data)
    except Exception as e:
        print(f"Error getting vendor monthly overview for {month}: {str(e)}")
        return {'total_vendors': 0, 'total_documents': 0, 'total_cost': 0.0}


def get_vendor_stats_from_r2(vendor_email):
    """Get vendor statistics from R2 storage (legacy function)"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # Look for vendor data
        vendor_prefix = f"vendor_register_details/{vendor_email}/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=vendor_prefix)
        
        stats = {
            'total_jobs': 0,
            'completed_jobs': 0,
            'pending_jobs': 0,
            'total_earnings': 0.0
        }
        
        if 'Contents' in objects:
            for obj in objects['Contents']:
                key = obj["Key"]
                if not key.endswith('/'):  # Skip folder entries
                    try:
                        head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                        metadata = head_response.get('Metadata', {})
                        
                        stats['total_jobs'] += 1
                        
                        if metadata.get('job_completed') == 'YES':
                            stats['completed_jobs'] += 1
                        else:
                            stats['pending_jobs'] += 1
                        
                        # Add earnings if available
                        if 'payment_amount' in metadata:
                            stats['total_earnings'] += float(metadata['payment_amount'])
                            
                    except Exception as e:
                        print(f"Error processing vendor data for {key}: {str(e)}")
                        continue
        
        return stats
        
    except Exception as e:
        print(f"Error getting vendor stats from R2: {str(e)}")
        return {
            'total_jobs': 0,
            'completed_jobs': 0,
            'pending_jobs': 0,
            'total_earnings': 0.0
        }


# Vendor Report Generation System
def generate_vendor_reports():
    """Generate vendor reports every 2 days at 11:30 PM IST"""
    try:
        # Get IST timezone
        ist = pytz.timezone('Asia/Kolkata')
        current_time = datetime.datetime.now(ist)
        
        # Check if it's 11:30 PM IST
        if current_time.hour == 23 and current_time.minute == 30:
            print(f"🕚 Generating vendor reports at {current_time.strftime('%Y-%m-%d %H:%M:%S')} IST")
            
            # Get all vendors
            vendors_data = get_all_vendors_from_r2()
            
            for vendor in vendors_data:
                vendor_id = vendor.get('vendor_id')
                if vendor_id:
                    # Generate report for this vendor
                    generate_single_vendor_report(vendor_id, current_time)
            
            print("✅ All vendor reports generated successfully")
            
    except Exception as e:
        print(f"❌ Error generating vendor reports: {str(e)}")


def generate_single_vendor_report(vendor_id, start_date, end_date, vendor_name, vendor_email):
    """Generate report for a single vendor for a specific date range"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # Get vendor documents for the date range with time constraint
        vendor_docs_data = process_vendor_documents_from_r2_date_range(s3, vendor_id, start_date, end_date, vendor_name, vendor_email)
        
        # Only generate report if there are documents
        if vendor_docs_data and vendor_docs_data.get('total_documents', 0) > 0:
            # Create report data
            report_data = {
                'vendor_id': vendor_id,
                'vendor_name': vendor_docs_data.get('vendor_name', 'Unknown'),
                'vendor_email': vendor_docs_data.get('email', ''),
                'report_date': end_date.isoformat(),
                'period_start': start_date.isoformat(),
                'period_end': end_date.isoformat(),
                'period_display': f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b')}",
                'total_documents': vendor_docs_data.get('total_documents', 0),
                'total_earning': vendor_docs_data.get('total_cost', 0.0),
                'service_breakdown': vendor_docs_data.get('service_breakdown', []),
                'payment_status': 'not completed',  # Default status
                'generated_at': datetime.datetime.now().isoformat(),
                'timezone': 'Asia/Kolkata'
            }
            
            # Sanitize email for folder name
            sanitized_email = vendor_email.replace('@', '_at_').replace('.', '_dot_')
            
            # Store report in R2 with proper naming
            report_filename = f"report_{start_date.strftime('%d_%b')}_to_{end_date.strftime('%d_%b')}.json"
            report_key = f"vendor_register_details/{sanitized_email}/transactionreports/{report_filename}"
            
            s3.put_object(
                Bucket=settings.R2_BUCKET,
                Key=report_key,
                Body=json.dumps(report_data, indent=2),
                ContentType='application/json'
            )
            
            print(f"📊 Generated report for vendor {vendor_id}: {vendor_docs_data.get('total_documents', 0)} documents, ₹{vendor_docs_data.get('total_cost', 0.0)}")
            return True
        else:
            print(f"⚠️ No documents found for vendor {vendor_id} in period {start_date} to {end_date}, skipping report generation")
            return False
            
    except Exception as e:
        print(f"❌ Error generating report for vendor {vendor_id}: {str(e)}")
        return False


def process_vendor_documents_from_r2_date_range(s3, vendor_id, start_date, end_date, vendor_name='Unknown', vendor_email=''):
    """Process vendor documents for a specific date range with time constraint (7 AM to 11:30 PM)"""
    try:
        total_documents = 0
        total_cost = 0.0
        service_breakdown = {}
        last_activity = None
        
        # Check both vendor_print_jobs and vendor_manual_print_jobs folders
        folders = [f"vendor_print_jobs/{vendor_id}/", f"vendor_manual_print_jobs/{vendor_id}/"]
        
        for folder in folders:
            objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=folder)
            
            if 'Contents' in objects:
                for obj in objects['Contents']:
                    key = obj["Key"]
                    filename = key.split('/')[-1]
                    
                    # Skip if it's just the folder itself
                    if filename == "":
                        continue
                    
                    try:
                        # Get file metadata
                        head_response = s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
                        metadata = head_response.get('Metadata', {})
                        
                        # Get last modified date
                        last_modified = obj.get('LastModified')
                        if not last_modified:
                            continue
                        
                        # Convert to IST for comparison
                        ist = pytz.timezone('Asia/Kolkata')
                        file_datetime = last_modified.astimezone(ist)
                        file_date = file_datetime.date()
                        file_time = file_datetime.time()
                        
                        # Filter by date range
                        if not (start_date <= file_date <= end_date):
                            continue
                        
                        # Filter by time constraint (7 AM to 11:30 PM)
                        if not (datetime.time(7, 0) <= file_time <= datetime.time(23, 30)):
                            continue
                        
                        # Count documents
                        total_documents += 1
                        
                        # Get service type
                        service_type = metadata.get('service_type', 'default')
                        if service_type not in service_breakdown:
                            service_breakdown[service_type] = {'count': 0, 'total_cost': 0.0}
                        
                        # Get pricing data
                        price = 0.0
                        if 'price' in metadata:
                            try:
                                price = float(metadata['price'])
                            except (ValueError, TypeError):
                                pass
                        elif 'total_price' in metadata:
                            try:
                                price = float(metadata['total_price'])
                            except (ValueError, TypeError):
                                pass
                        
                        # Update totals
                        total_cost += price
                        
                        # Update service breakdown
                        service_breakdown[service_type]['count'] += 1
                        service_breakdown[service_type]['total_cost'] += price
                        
                        # Update last activity
                        if not last_activity or last_modified > last_activity:
                            last_activity = last_modified
                            
                    except Exception as e:
                        print(f"Error processing vendor document {key}: {str(e)}")
                        continue
        
        # Convert service breakdown to list format
        service_breakdown_list = [
            {
                'name': service, 
                'count': data['count'],
                'total_cost': round(data['total_cost'], 2)
            } 
            for service, data in service_breakdown.items()
        ]
        
        return {
            'vendor_name': vendor_name,
            'email': vendor_email,
            'total_documents': total_documents,
            'service_breakdown': service_breakdown_list,
            'total_cost': round(total_cost, 2),
            'last_activity': last_activity
        }
        
    except Exception as e:
        print(f"Error processing vendor documents for {vendor_id}: {str(e)}")
        return None


def get_vendor_reports_for_history(request):
    """Get vendor reports for history section (no auth required)"""
    try:
        vendor_id = request.GET.get('vendor_id')
        month = request.GET.get('month')
        
        if not vendor_id:
            return JsonResponse({
                'success': False,
                'error': 'Vendor ID is required'
            }, status=400)
        
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # First, find the vendor's email to get the correct path
        vendor_email = ''
        try:
            reg_prefix = "vendor_register_details/"
            reg_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reg_prefix)
            
            if 'Contents' in reg_objects:
                for obj in reg_objects['Contents']:
                    key = obj["Key"]
                    if key.endswith('registration_details.json'):
                        try:
                            response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                            reg_data = json.loads(response['Body'].read().decode('utf-8'))
                            
                            if reg_data.get('vendor_id') == vendor_id:
                                vendor_email = reg_data.get('vendor_email', '')
                                # If vendor_email is not in the data, extract from folder path
                                if not vendor_email:
                                    # Extract email from folder path: vendor_register_details/email_at_domain_dot_com/
                                    folder_path = key.split('/')[1]  # Get the folder name
                                    vendor_email = folder_path.replace('_at_', '@').replace('_dot_', '.')
                                break
                        except Exception as e:
                            print(f"Error reading vendor registration {key}: {str(e)}")
                            continue
        except Exception as e:
            print(f"Error getting vendor email for {vendor_id}: {str(e)}")
        
        if not vendor_email:
            return JsonResponse({
                'success': False,
                'error': 'Vendor not found'
            }, status=404)
        
        # Sanitize email for folder name
        sanitized_email = vendor_email.replace('@', '_at_').replace('.', '_dot_')
        
        # List all reports for this vendor
        reports_prefix = f"vendor_register_details/{sanitized_email}/transactionreports/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reports_prefix)
        
        reports = []
        available_months = set()
        
        if 'Contents' in objects:
            for obj in objects['Contents']:
                key = obj["Key"]
                if key.endswith('.json'):
                    try:
                        # Get report data
                        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                        report_data = json.loads(response['Body'].read().decode('utf-8'))
                        
                        # Add month to available months
                        report_date_str = report_data.get('generated_at', report_data.get('report_date', ''))
                        if report_date_str:
                            report_date = datetime.datetime.fromisoformat(report_date_str.replace('Z', '+00:00'))
                            report_month = report_date.strftime('%Y-%m')
                            available_months.add(report_month)
                            
                            # Filter by month if specified
                            if month and report_month != month:
                                continue
                        
                        reports.append(report_data)
                        
                    except Exception as e:
                        print(f"Error reading report {key}: {str(e)}")
                        continue
        
        # Sort by report date (newest first)
        reports.sort(key=lambda x: x.get('generated_at', x.get('report_date', '')), reverse=True)
        
        # Convert available months to sorted list
        available_months_list = sorted(list(available_months), reverse=True)
        
        return JsonResponse({
            'success': True,
            'reports': reports,
            'available_months_list': available_months_list,
            'total_count': len(reports)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@staff_member_required
def download_vendor_monthly_report(request):
    """Download monthly report for a vendor"""
    try:
        vendor_id = request.GET.get('vendor_id')
        month = request.GET.get('month')
        
        if not vendor_id or not month:
            return JsonResponse({
                'success': False,
                'error': 'Vendor ID and month are required'
            }, status=400)
        
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # Get all reports for the month
        reports_prefix = f"vendor_register_details/{vendor_id}/transactionreports/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reports_prefix)
        
        monthly_reports = []
        total_documents = 0
        total_earning = 0.0
        
        if 'Contents' in objects:
            for obj in objects['Contents']:
                key = obj["Key"]
                if key.endswith('.json'):
                    try:
                        # Get report data
                        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                        report_data = json.loads(response['Body'].read().decode('utf-8'))
                        
                        # Filter by month
                        report_date = datetime.datetime.fromisoformat(report_data['report_date'].replace('Z', '+00:00'))
                        report_month = report_date.strftime('%Y-%m')
                        if report_month == month:
                            monthly_reports.append(report_data)
                            total_documents += report_data['total_documents']
                            total_earning += report_data['total_earning']
                            
                    except Exception as e:
                        print(f"Error reading report {key}: {str(e)}")
                        continue
        
        # Create monthly summary
        monthly_summary = {
            'vendor_id': vendor_id,
            'month': month,
            'total_reports': len(monthly_reports),
            'total_documents': total_documents,
            'total_earning': round(total_earning, 2),
            'reports': monthly_reports,
            'generated_at': datetime.datetime.now().isoformat()
        }
        
        # Create CSV content
        csv_content = f"Vendor Monthly Report - {month}\n"
        csv_content += f"Vendor ID: {vendor_id}\n"
        csv_content += f"Total Reports: {len(monthly_reports)}\n"
        csv_content += f"Total Documents: {total_documents}\n"
        csv_content += f"Total Earning: ₹{total_earning:.2f}\n\n"
        csv_content += "Date,Documents,Earning,Service Breakdown\n"
        
        for report in monthly_reports:
            service_breakdown = ', '.join([f"{s['name']}({s['count']})" for s in report['service_breakdown']])
            csv_content += f"{report['report_date'][:10]},{report['total_documents']},₹{report['total_earning']:.2f},{service_breakdown}\n"
        
        # Return CSV file
        response = HttpResponse(csv_content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="vendor_report_{vendor_id}_{month}.csv"'
        return response
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def get_vendor_pricing_creation_date(s3, vendor_email):
    """Get the creation date of pricing.json for a vendor from the created_at field"""
    try:
        sanitized_email = vendor_email.replace('@', '_at_').replace('.', '_dot_')
        pricing_key = f"vendor_register_details/{sanitized_email}/pricing.json"
        
        # Get the actual pricing.json file content
        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=pricing_key)
        pricing_data = json.loads(response['Body'].read().decode('utf-8'))
        
        # Extract created_at from the pricing data
        created_at_str = pricing_data.get('created_at')
        if created_at_str:
            # Parse the ISO format datetime
            created_at = datetime.datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            
            # Convert to IST
            ist = pytz.timezone('Asia/Kolkata')
            creation_date_ist = created_at.astimezone(ist)
            
            return creation_date_ist.date()
        else:
            # Fallback to file modification date if created_at is not available
            response = s3.head_object(Bucket=settings.R2_BUCKET, Key=pricing_key)
            creation_date = response['LastModified']
            
            # Convert to IST
            ist = pytz.timezone('Asia/Kolkata')
            creation_date_ist = creation_date.astimezone(ist)
            
            return creation_date_ist.date()
            
    except Exception as e:
        print(f"Error getting pricing creation date for {vendor_email}: {str(e)}")
        return None


def get_existing_reports(s3, vendor_email):
    """Get list of existing reports for a vendor"""
    try:
        sanitized_email = vendor_email.replace('@', '_at_').replace('.', '_dot_')
        reports_prefix = f"vendor_register_details/{sanitized_email}/transactionreports/"
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reports_prefix)
        
        existing_reports = set()
        
        if 'Contents' in objects:
            for obj in objects['Contents']:
                key = obj["Key"]
                if key.endswith('.json'):
                    # Extract date range from filename
                    filename = key.split('/')[-1]
                    if filename.startswith('report_') and filename.endswith('.json'):
                        # Parse filename like "report_30_Jul_to_01_Aug.json"
                        date_part = filename.replace('report_', '').replace('.json', '')
                        existing_reports.add(date_part)
        
        return existing_reports
    except Exception as e:
        print(f"Error getting existing reports for {vendor_email}: {str(e)}")
        return set()


def generate_comprehensive_reports():
    """Generate comprehensive reports for all vendors from pricing.json creation date"""
    try:
        print("🔄 Generating comprehensive reports for all vendors...")
        
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')
        
        # Get all vendors
        vendors_data = get_all_vendors_from_r2()
        
        for vendor in vendors_data:
            vendor_id = vendor.get('vendor_id')
            vendor_name = vendor.get('vendor_name', 'Unknown')
            vendor_email = vendor.get('email', '')
            
            if not vendor_id or not vendor_email:
                continue
                
            print(f"\n📊 Processing vendor: {vendor_name} ({vendor_email})")
            
            # Get pricing creation date
            pricing_creation_date = get_vendor_pricing_creation_date(s3, vendor_email)
            if not pricing_creation_date:
                print(f"  ⚠️ No pricing.json found for {vendor_email}, skipping")
                continue
            
            print(f"  📅 Pricing created on: {pricing_creation_date}")
            
            # Get existing reports
            existing_reports = get_existing_reports(s3, vendor_email)
            print(f"  📋 Found {len(existing_reports)} existing reports")
            
            # Generate reports from pricing creation date to current date (every 2 days)
            current_date = datetime.datetime.now(pytz.timezone('Asia/Kolkata')).date()
            start_date = pricing_creation_date
            
            # Generate reports in 2-day intervals
            current_period_start = start_date
            reports_generated = 0
            
            while current_period_start < current_date:
                # Calculate end date (2 days later, but not beyond current date)
                current_period_end = min(current_period_start + datetime.timedelta(days=1), current_date)
                
                # Create filename for this period
                period_filename = f"{current_period_start.strftime('%d_%b')}_to_{current_period_end.strftime('%d_%b')}"
                
                # Check if report already exists
                if period_filename in existing_reports:
                    print(f"  ✅ Report for {period_filename} already exists, skipping")
                else:
                    # Generate report for this period
                    success = generate_single_vendor_report(
                        vendor_id, 
                        current_period_start, 
                        current_period_end, 
                        vendor_name, 
                        vendor_email
                    )
                    if success:
                        reports_generated += 1
                
                # Move to next period (2 days after the start of current period)
                current_period_start = current_period_start + datetime.timedelta(days=2)
            
            print(f"  ✅ Generated {reports_generated} new reports for {vendor_name}")
        
        print("\n✅ Comprehensive report generation completed!")
        
    except Exception as e:
        print(f"❌ Error generating comprehensive reports: {str(e)}")


def trigger_report_generation():
    """Trigger report generation manually"""
    try:
        print("🔄 Triggering manual report generation...")
        generate_comprehensive_reports()
        return True
    except Exception as e:
        print(f"❌ Error in manual report generation: {str(e)}")
        return False


@staff_member_required
def trigger_report_generation_view(request):
    """View to manually trigger report generation"""
    try:
        success = trigger_report_generation()
        if success:
            return JsonResponse({
                'success': True,
                'message': 'Report generation completed successfully!'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Error occurred during report generation'
            }, status=500)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)


def run_daily_report_generation():
    """Run report generation at 12 AM IST every day"""
    try:
        # Get current IST time
        ist = pytz.timezone('Asia/Kolkata')
        current_time = dt.now(ist)
        
        print(f"🕛 Running daily report generation at {current_time.strftime('%Y-%m-%d %H:%M:%S IST')}")
        
        # Generate reports for all vendors
        generate_comprehensive_reports()
        
        print("✅ Daily report generation completed successfully!")
        
    except Exception as e:
        print(f"❌ Error in daily report generation: {str(e)}")


def start_automatic_report_generation():
    """Start automatic report generation scheduler"""
    def run_scheduler():
        # Schedule report generation every day at 12:00 AM IST
        schedule.every().day.at("00:00").do(run_daily_report_generation)
        
        print("✅ Automatic report generation scheduler started!")
        print("📅 Reports will be generated daily at 12:00 AM IST")
        
        # Run the scheduler in a loop
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                print(f"❌ Error in scheduler: {str(e)}")
                time.sleep(300)  # Wait 5 minutes before retrying
    
    # Start the background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    print("🚀 Background report generation scheduler initialized!")


# Initialize automatic report generation when the module is imported
start_automatic_report_generation()


def generate_historical_reports():
    """Generate historical reports for all existing data (legacy function)"""
    generate_comprehensive_reports()


@staff_member_required
def admin_transactions_data(request):
    """Get all vendor transaction reports for admin dashboard with optional month filter"""
    try:
        selected_month = request.GET.get('month')  # format YYYY-MM

        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Collect all vendor emails from registration files
        reg_prefix = "vendor_register_details/"
        reg_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reg_prefix)

        all_reports = []
        available_months = set()

        if 'Contents' in reg_objects:
            for obj in reg_objects['Contents']:
                key = obj["Key"]
                if key.endswith('registration_details.json'):
                    try:
                        response = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                        reg_data = json.loads(response['Body'].read().decode('utf-8'))

                        vendor_email = reg_data.get('vendor_email', '')
                        vendor_name = reg_data.get('vendor_name', 'Unknown')
                        vendor_id = reg_data.get('vendor_id')

                        # Fallback: infer email from folder
                        if not vendor_email:
                            folder_path = key.split('/')[1]
                            vendor_email = folder_path.replace('_at_', '@').replace('_dot_', '.')

                        if not vendor_email:
                            continue

                        sanitized_email = vendor_email.replace('@', '_at_').replace('.', '_dot_')
                        reports_prefix = f"vendor_register_details/{sanitized_email}/transactionreports/"
                        rep_objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=reports_prefix)

                        if 'Contents' in rep_objects:
                            for robj in rep_objects['Contents']:
                                rkey = robj['Key']
                                if not rkey.endswith('.json'):
                                    continue
                                try:
                                    rresp = s3.get_object(Bucket=settings.R2_BUCKET, Key=rkey)
                                    report_data = json.loads(rresp['Body'].read().decode('utf-8'))

                                    # Compute month for filtering and available months
                                    report_date_str = report_data.get('generated_at', report_data.get('report_date', ''))
                                    report_month = None
                                    if report_date_str:
                                        try:
                                            rdt = datetime.datetime.fromisoformat(report_date_str.replace('Z', '+00:00'))
                                            report_month = rdt.strftime('%Y-%m')
                                            available_months.add(report_month)
                                        except Exception:
                                            pass

                                    if selected_month and report_month and report_month != selected_month:
                                        continue

                                    # Attach identification fields to allow updates from admin UI
                                    report_data['__vendor_email'] = vendor_email
                                    report_data['__vendor_name'] = vendor_name
                                    report_data['__vendor_id'] = vendor_id
                                    report_data['__report_key'] = rkey

                                    all_reports.append(report_data)
                                except Exception as e:
                                    print(f"Error reading report {rkey}: {str(e)}")
                                    continue
                    except Exception as e:
                        print(f"Error reading vendor registration {key}: {str(e)}")
                        continue

        # Sort newest first
        all_reports.sort(key=lambda x: x.get('generated_at', x.get('report_date', '')), reverse=True)
        
        return JsonResponse({
            'success': True,
            'transactions': all_reports,
            'available_months': sorted(list(available_months), reverse=True),
            'total_count': len(all_reports)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@staff_member_required
def admin_update_report_payment_status(request):
    """Update a specific report's payment_status field (e.g., not completed -> completed)"""
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

        data = json.loads(request.body or '{}')
        vendor_email = data.get('vendor_email')
        report_key = data.get('report_key')  # full key preferred
        new_status = data.get('payment_status', 'completed')

        if not vendor_email:
            return JsonResponse({'success': False, 'error': 'vendor_email is required'}, status=400)

        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Resolve report key if not provided but period given
        if not report_key:
            # Try to reconstruct using period_start and period_end
            period_start = data.get('period_start')  # YYYY-MM-DD
            period_end = data.get('period_end')      # YYYY-MM-DD
            if not period_start or not period_end:
                return JsonResponse({'success': False, 'error': 'report_key or period_start/period_end required'}, status=400)

            try:
                ps = datetime.datetime.fromisoformat(period_start).date()
                pe = datetime.datetime.fromisoformat(period_end).date()
            except Exception:
                return JsonResponse({'success': False, 'error': 'Invalid period dates'}, status=400)

            sanitized_email = vendor_email.replace('@', '_at_').replace('.', '_dot_')
            filename = f"report_{ps.strftime('%d_%b')}_to_{pe.strftime('%d_%b')}.json"
            report_key = f"vendor_register_details/{sanitized_email}/transactionreports/{filename}"

        # Fetch, modify, and write back the report JSON
        rresp = s3.get_object(Bucket=settings.R2_BUCKET, Key=report_key)
        report_data = json.loads(rresp['Body'].read().decode('utf-8'))
        report_data['payment_status'] = new_status
        report_data['updated_at'] = datetime.datetime.now().isoformat()

        s3.put_object(
            Bucket=settings.R2_BUCKET,
            Key=report_key,
            Body=json.dumps(report_data, indent=2),
            ContentType='application/json'
        )

        return JsonResponse({'success': True, 'report': report_data})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_member_required
def admin_contacts_data(request):
    """Get all contacts data for admin dashboard"""
    try:
        # This would typically come from a contacts model
        # For now, return placeholder data
        contacts_data = []
        
        return JsonResponse({
            'success': True,
            'contacts': contacts_data,
            'total_count': len(contacts_data)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@staff_member_required
def admin_installations_data(request):
    """Get all installation data for admin dashboard"""
    try:
        # This would typically come from installation tracking
        # For now, return placeholder data
        installations_data = []
        
        return JsonResponse({
            'success': True,
            'installations': installations_data,
            'total_count': len(installations_data)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@staff_member_required
def admin_activity_data(request):
    """Get all activity data for admin dashboard"""
    try:
        # This would typically come from activity logs
        # For now, return placeholder data
        activity_data = []
        
        return JsonResponse({
            'success': True,
            'activities': activity_data,
            'total_count': len(activity_data)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# Support Availability Calendar (Admin)
@staff_member_required
@require_http_methods(["GET"])
def admin_support_availability_get(request):
    """Return availability calendar JSON for a given month (YYYY-MM)."""
    try:
        month = request.GET.get('month')  # format YYYY-MM
        if not month:
            return JsonResponse({'success': False, 'error': 'month is required (YYYY-MM)'}, status=400)

        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Build key: folder + month-name.json (use correct spelling; fallback to legacy misspelling)
        year, mon = month.split('-')
        month_name = dt(int(year), int(mon), 1).strftime('%B %Y')  # e.g., 'September 2025'
        correct_folder = "Printmax Support availability Calendar"
        legacy_folder = "Printmax Support avialablity Calendar"
        calendar_key = f"{correct_folder}/{month_name}.json"
        month_data = { 'dates': {} }
        exists = False
        try:
            resp = s3.get_object(Bucket=settings.R2_BUCKET, Key=calendar_key)
            month_data = json.loads(resp['Body'].read().decode('utf-8'))
            exists = True
        except Exception:
            # Fallback to legacy folder if present
            try:
                legacy_key = f"{legacy_folder}/{month_name}.json"
                resp = s3.get_object(Bucket=settings.R2_BUCKET, Key=legacy_key)
                month_data = json.loads(resp['Body'].read().decode('utf-8'))
                exists = True
            except Exception:
                month_data = { 'dates': {} }

        return JsonResponse({'success': True, 'month': month, 'exists': exists, 'data': month_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_member_required
@require_http_methods(["POST"])
def admin_support_availability_save(request):
    """Save availability for a given month. Body: { month: 'YYYY-MM', dates: { 'YYYY-MM-DD': [slot,...] } }"""
    try:
        body = json.loads(request.body or '{}')
        month = body.get('month')
        dates = body.get('dates', {})
        if not month or not isinstance(dates, dict):
            return JsonResponse({'success': False, 'error': 'month and dates required'}, status=400)

        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        # Persist as separate file per month in folder
        year, mon = month.split('-')
        month_name = dt(int(year), int(mon), 1).strftime('%B %Y')
        calendar_key = f"Printmax Support availability Calendar/{month_name}.json"

        s3.put_object(
            Bucket=settings.R2_BUCKET,
            Key=calendar_key,
            Body=json.dumps({ 'dates': dates }, indent=2),
            ContentType='application/json'
        )

        return JsonResponse({'success': True, 'month': month, 'data': { 'dates': dates }})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# Vendor installations: list and update registration details
@staff_member_required
@require_http_methods(["GET"])
def admin_installations_list(request):
    """List vendor registrations (vendor name, email, id, coordinator, shop_visited)"""
    try:
        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        prefix = 'vendor_register_details/'
        pending = []
        counts = { 'pending': 0, 'completed': 0, 'assigned': 0 }

        # List top-level vendor folders
        objects = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=prefix)
        for obj in objects.get('Contents', []):
            key = obj['Key']
            # Only look at files named registration.json or registration_details.json
            if key.endswith('registration.json') or key.endswith('registration_details.json'):
                try:
                    resp = s3.get_object(Bucket=settings.R2_BUCKET, Key=key)
                    reg = json.loads(resp['Body'].read().decode('utf-8'))
                except Exception:
                    continue

                coordinator = reg.get('coordinator')
                shop_visited = reg.get('shop_visited')
                # Skip vendors that do not have both fields present
                if coordinator is None or shop_visited is None:
                    continue

                coordinator_norm = (str(coordinator) or 'none').strip().lower()
                shop_visited_norm = (str(shop_visited) or 'not visited').strip().lower()

                email = reg.get('vendor_email', '')
                if not email:
                    # infer from folder path vendor_register_details/<sanitized_email>/registration*.json
                    try:
                        folder = key.split('/')[1]
                        email = folder.replace('_at_', '@').replace('_dot_', '.')
                    except Exception:
                        email = ''

                # Attempt to read appointment details for this vendor
                appointment_date = ''
                appointment_slot = ''
                if email:
                    try:
                        appt_key = f"vendor_register_details/{email.replace('@','_at_').replace('.','_dot_')}/appointment.json"
                        aresp = s3.get_object(Bucket=settings.R2_BUCKET, Key=appt_key)
                        appt = json.loads(aresp['Body'].read().decode('utf-8'))
                        appointment_date = appt.get('appointment_date', '')
                        appointment_slot = appt.get('appointment_slot', '')
                    except Exception:
                        pass

                # Count completed/pending
                if shop_visited_norm == 'visited':
                    counts['completed'] += 1
                else:
                    counts['pending'] += 1
                if coordinator_norm != 'none':
                    counts['assigned'] += 1

                # Return only strictly pending vendors (coordinator == none and not visited)
                if coordinator_norm == 'none' and shop_visited_norm == 'not visited' and email:
                    pending.append({
                        'vendor_name': reg.get('vendor_name', ''),
                        'vendor_email': email,
                        'vendor_id': reg.get('vendor_id', ''),
                        'coordinator': coordinator,
                        'shop_visited': shop_visited,
                        'appointment_date': appointment_date,
                        'appointment_slot': appointment_slot,
                        'latitude': reg.get('latitude', '0'),
                        'longitude': reg.get('longitude', '0')
                    })

        return JsonResponse({'success': True, 'vendors': pending, 'counts': counts})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def admin_update_vendor_location(request):
    """Update vendor latitude or longitude in registration details"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        email = data.get('email')
        field = data.get('field')  # 'latitude' or 'longitude'
        value = data.get('value', '0')
        
        if not email or field not in ['latitude', 'longitude']:
            return JsonResponse({'success': False, 'error': 'Invalid parameters'}, status=400)
        
        # Sanitize email for file path
        sanitized_email = email.replace('@', '_at_').replace('.', '_dot_')
        file_key = f"vendor_register_details/{sanitized_email}/registration.json"
        
        # Read current registration data
        try:
            response = s3.get_object(Bucket=settings.R2_BUCKET, Key=file_key)
            registration_data = json.loads(response['Body'].read().decode('utf-8'))
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Failed to read registration data: {str(e)}'}, status=404)
        
        # Update the field
        registration_data[field] = value
        
        # Save back to R2
        s3.put_object(
            Bucket=settings.R2_BUCKET,
            Key=file_key,
            Body=json.dumps(registration_data, indent=2),
            ContentType='application/json'
        )
        
        return JsonResponse({'success': True, 'message': f'{field} updated successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_member_required
@require_http_methods(["POST"])
def admin_installations_update(request):
    """Update coordinator, shop_visited, latitude, and longitude in registration_details.json for a vendor."""
    try:
        payload = json.loads(request.body or '{}')
        vendor_email = payload.get('vendor_email')
        coordinator = payload.get('coordinator')
        mark_visited = bool(payload.get('shop_visited', True))
        latitude = payload.get('latitude', '0')
        longitude = payload.get('longitude', '0')
        
        if not vendor_email or not coordinator:
            return JsonResponse({'success': False, 'error': 'vendor_email and coordinator required'}, status=400)

        s3 = boto3.client('s3',
                          aws_access_key_id=settings.R2_ACCESS_KEY,
                          aws_secret_access_key=settings.R2_SECRET_KEY,
                          endpoint_url=settings.R2_ENDPOINT,
                          region_name='auto')

        reg_key = f"vendor_register_details/{vendor_email.replace('@','_at_').replace('.','_dot_')}/registration_details.json"
        resp = s3.get_object(Bucket=settings.R2_BUCKET, Key=reg_key)
        reg = json.loads(resp['Body'].read().decode('utf-8'))

        reg['coordinator'] = coordinator
        reg['shop_visited'] = 'visited' if mark_visited else 'not visited'
        reg['latitude'] = latitude
        reg['longitude'] = longitude

        s3.put_object(Bucket=settings.R2_BUCKET, Key=reg_key, Body=json.dumps(reg, indent=2), ContentType='application/json')

        return JsonResponse({'success': True, 'vendor_email': vendor_email, 'data': reg})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
