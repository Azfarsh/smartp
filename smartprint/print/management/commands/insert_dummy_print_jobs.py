"""
Django management command to insert dummy data into User_print_jobs and Vendor_print_jobs tables
via the Cloudflare Worker API.

Usage:
    python manage.py insert_dummy_print_jobs
    python manage.py insert_dummy_print_jobs --count 10
"""

import json
import datetime
import random
import uuid
from django.core.management.base import BaseCommand
from django.conf import settings
import requests


class Command(BaseCommand):
    help = 'Insert dummy print job data into D1 database via Worker API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=5,
            help='Number of dummy records to insert for each table (default: 5)'
        )

    def handle(self, *args, **options):
        count = options['count']
        api_url = getattr(settings, 'WORKER_API_URL', '')
        api_key = getattr(settings, 'WORKER_API_KEY', '')

        if not api_url or not api_key:
            self.stdout.write(
                self.style.ERROR('❌ Worker API not configured. Set WORKER_API_URL and WORKER_API_KEY in settings.')
            )
            return

        self.stdout.write(self.style.SUCCESS(f'🚀 Starting to insert {count} dummy records into each table...'))

        # Sample data for generating realistic dummy records
        service_types = [
            'digital_print', 'photo_print', 'passport_photo', 'jumbo_printing',
            'gloss_printing', 'golden_embossing', 'regular_print'
        ]
        colors = ['Color', 'Black and White', 'Mixed']
        orientations = ['portrait', 'landscape']
        statuses = ['pending', 'processing', 'completed']
        vendors = ['firozshop', 'testvendor1', 'testvendor2']
        user_emails = [
            'user1@example.com', 'user2@example.com', 'user3@example.com',
            'test@example.com', 'demo@example.com'
        ]

        success_count_user = 0
        success_count_vendor = 0
        error_count = 0

        # Insert dummy data into User_print_jobs
        self.stdout.write(self.style.WARNING('\n📝 Inserting dummy data into User_print_jobs table...'))
        for i in range(count):
            timestamp = datetime.datetime.now().isoformat()
            # Use unique user email for each record to avoid conflicts
            user_email = f'test_user_{uuid.uuid4().hex[:8]}@example.com'
            # Generate truly unique filename with UUID
            unique_id = uuid.uuid4().hex[:12]
            filename = f'dummy_document_{i+1}_{unique_id}_{int(datetime.datetime.now().timestamp())}.pdf'
            service_type = random.choice(service_types)
            
            pricing_details = {
                'total_price': round(random.uniform(50, 500), 2),
                'pricing_breakdown': {
                    'price_per_page': round(random.uniform(2, 10), 2),
                    'page_count': random.randint(1, 50),
                    'num_copies': random.randint(1, 5),
                    'pricing_key_used': f'{service_type}_a4'
                },
                'calculation_timestamp': timestamp
            }

            payload = {
                'vendor_id': random.choice(vendors),
                'vendor_email': f'vendor{random.randint(1,3)}@example.com',
                'user_email': user_email,
                'filename': filename,
                'storage_folder': 'users',
                'r2_path': f'users/{user_email}/{filename}',
                'service_type': service_type,
                'status': random.choice(statuses),
                'job_completed': 'NO' if random.random() > 0.3 else 'YES',
                'vendor_status': 'not sended' if random.random() > 0.5 else 'sended',
                'token': f'TOK{random.randint(1000, 9999)}',
                'job_id': f'JOB{random.randint(10000, 99999)}',
                'copies': str(random.randint(1, 5)),
                'color': random.choice(colors),
                'orientation': random.choice(orientations),
                'pageSize': 'A4',
                'pageRange': 'all',
                'specificPages': '',
                'spiralBinding': 'No',
                'lamination': 'No',
                'service_name': service_type.replace('_', ' ').title(),
                'feedback': f'Dummy feedback for job {i+1}',
                'quality': 'standard_quality',
                'thickness': '',
                'points_applied': 'false',
                'points_used': 0,
                'timestamp': timestamp,
                'completion_time': '',
                'rendered_status': 'NO',
                'trash': 'NO',
                'total_price': pricing_details['total_price'],
                'platform_profit': round(pricing_details['total_price'] * 0.15, 2),
                'price_per_page': pricing_details['pricing_breakdown']['price_per_page'],
                'final_amount': pricing_details['total_price'],
                'page_count': pricing_details['pricing_breakdown']['page_count'],
                'num_copies': pricing_details['pricing_breakdown']['num_copies'],
                'pricing_details': json.dumps(pricing_details)
            }

            try:
                worker_endpoint = api_url.rstrip('/') + '/add-user-print-job'
                resp = requests.post(
                    worker_endpoint,
                    json=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'x-api-key': api_key
                    },
                    timeout=10
                )

                if resp.status_code == 200:
                    success_count_user += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✅ User job {i+1}: {filename}')
                    )
                else:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(f'  ❌ User job {i+1} failed: {resp.status_code} - {resp.text[:100]}')
                    )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'  ❌ User job {i+1} error: {str(e)[:100]}')
                )

        # Insert dummy data into Vendor_print_jobs
        self.stdout.write(self.style.WARNING('\n📝 Inserting dummy data into Vendor_print_jobs table...'))
        for i in range(count):
            timestamp = datetime.datetime.now().isoformat()
            vendor_id = random.choice(vendors)
            # Use unique user email for each record to avoid conflicts
            user_email = f'test_user_{uuid.uuid4().hex[:8]}@example.com'
            # Generate truly unique filename with UUID
            unique_id = uuid.uuid4().hex[:12]
            filename = f'dummy_vendor_job_{i+1}_{unique_id}_{int(datetime.datetime.now().timestamp())}.pdf'
            service_type = random.choice(service_types)
            storage_folder = random.choice(['vendor_print_jobs', 'vendor_manual_print_jobs'])
            
            pricing_details = {
                'total_price': round(random.uniform(50, 500), 2),
                'pricing_breakdown': {
                    'price_per_page': round(random.uniform(2, 10), 2),
                    'page_count': random.randint(1, 50),
                    'num_copies': random.randint(1, 5),
                    'pricing_key_used': f'{service_type}_a4'
                },
                'calculation_timestamp': timestamp
            }

            payload = {
                'vendor_id': vendor_id,
                'vendor_email': f'vendor{random.randint(1,3)}@example.com',
                'user_email': user_email,
                'filename': filename,
                'storage_folder': storage_folder,
                'r2_path': f'{storage_folder}/{vendor_id}/{filename}',
                'service_type': service_type,
                'status': random.choice(statuses),
                'job_completed': 'NO' if random.random() > 0.3 else 'YES',
                'vendor_status': 'not sended' if random.random() > 0.5 else 'sended',
                'token': f'TOK{random.randint(1000, 9999)}',
                'job_id': f'JOB{random.randint(10000, 99999)}',
                'copies': str(random.randint(1, 5)),
                'color': random.choice(colors),
                'orientation': random.choice(orientations),
                'pageSize': 'A4',
                'pageRange': 'all',
                'specificPages': '',
                'spiralBinding': 'No',
                'lamination': 'No',
                'service_name': service_type.replace('_', ' ').title(),
                'feedback': f'Dummy vendor job {i+1}',
                'quality': 'standard_quality',
                'thickness': '',
                'points_applied': 'false',
                'points_used': 0,
                'timestamp': timestamp,
                'completion_time': '',
                'rendered_status': 'NO',
                'trash': 'NO',
                'total_price': pricing_details['total_price'],
                'platform_profit': round(pricing_details['total_price'] * 0.15, 2),
                'price_per_page': pricing_details['pricing_breakdown']['price_per_page'],
                'final_amount': pricing_details['total_price'],
                'page_count': pricing_details['pricing_breakdown']['page_count'],
                'num_copies': pricing_details['pricing_breakdown']['num_copies'],
                'pricing_details': json.dumps(pricing_details)
            }

            try:
                worker_endpoint = api_url.rstrip('/') + '/add-vendor-print-job'
                resp = requests.post(
                    worker_endpoint,
                    json=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'x-api-key': api_key
                    },
                    timeout=10
                )

                if resp.status_code == 200:
                    success_count_vendor += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✅ Vendor job {i+1}: {filename} ({storage_folder})')
                    )
                else:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(f'  ❌ Vendor job {i+1} failed: {resp.status_code} - {resp.text[:100]}')
                    )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'  ❌ Vendor job {i+1} error: {str(e)[:100]}')
                )

        # Summary
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Summary:\n'
            f'   User_print_jobs: {success_count_user}/{count} successful\n'
            f'   Vendor_print_jobs: {success_count_vendor}/{count} successful\n'
            f'   Errors: {error_count}'
        ))

        if success_count_user > 0 or success_count_vendor > 0:
            self.stdout.write(self.style.SUCCESS(
                '\n🎉 Dummy data insertion completed! Check your D1 database to verify the records.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                '\n⚠️ No records were inserted. Please check your Worker API configuration.'
            ))

