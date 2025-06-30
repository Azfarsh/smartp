import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import logging
from . import views

logger = logging.getLogger(__name__)

class VendorConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Handle WebSocket connection for vendor client"""
        self.vendor_id = self.scope['url_route']['kwargs']['vendor_id']
        self.room_group_name = f'vendor_{self.vendor_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"Enhanced Vendor {self.vendor_id} connected")
        
        # Send initial status
        await self.send(text_data=json.dumps({
            'type': 'connection_status',
            'status': 'connected',
            'vendor_id': self.vendor_id,
            'message': 'Enhanced vendor client connected successfully'
        }))

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        logger.info(f"Enhanced Vendor {self.vendor_id} disconnected")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages from vendor client"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'request_print_jobs':
                # Enhanced request handling with R2 folder structure validation
                await self.handle_print_jobs_request(data)
                
            elif message_type == 'job_completed':
                # Handle job completion notification
                await self.handle_job_completed(data)
                
            elif message_type == 'job_failed':
                # Handle job failure notification
                await self.handle_job_failed(data)
                
            elif message_type == 'status_update':
                # Handle vendor client status updates
                await self.handle_status_update(data)
                
            elif message_type == 'printer_status':
                # Handle printer status updates
                await self.handle_printer_status(data)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received from vendor client")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except Exception as e:
            logger.error(f"Error processing vendor message: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error processing message: {str(e)}'
            }))

    async def handle_print_jobs_request(self, data):
        """Handle print job requests with enhanced R2 folder structure validation"""
        try:
            vendor_id = data.get('vendor_id')
            r2_folder_structure = data.get('r2_folder_structure', {})
            queue_status = data.get('queue_status', {})
            
            logger.info(f"Enhanced print jobs requested by vendor {vendor_id}")
            
            # Get pending jobs with R2 folder structure validation
            pending_jobs = await self.get_enhanced_pending_jobs(vendor_id, r2_folder_structure)
            
            if not pending_jobs:
                await self.send(text_data=json.dumps({
                    'type': 'print_jobs_response',
                    'message': 'No pending print jobs with valid R2 structure',
                    'jobs': [],
                    'vendor_id': vendor_id
                }))
                return
            
            # Send jobs with enhanced structure validation
            validated_jobs = []
            for job in pending_jobs:
                if self.validate_job_r2_structure(job, r2_folder_structure):
                    validated_jobs.append(job)
                else:
                    logger.warning(f"Job {job.get('filename')} failed R2 structure validation")
            
            if validated_jobs:
                # Send jobs one by one with small delays to prevent overwhelming
                for job in validated_jobs:
                    await self.send(text_data=json.dumps({
                        'type': 'print_job',
                        'job': {
                            'filename': job['filename'],
                            'download_url': job['download_url'],
                            'metadata': job['metadata'],
                            'user_email': job.get('user_email', ''),
                            'r2_path': job.get('r2_path', ''),
                            'validation_status': 'valid'
                        },
                        'vendor_id': vendor_id
                    }))
                    
                    # Small delay between jobs
                    await asyncio.sleep(0.3)
                
                logger.info(f"Sent {len(validated_jobs)} validated print jobs to vendor {vendor_id}")
            else:
                await self.send(text_data=json.dumps({
                    'type': 'print_jobs_response',
                    'message': 'No jobs passed R2 structure validation',
                    'jobs': [],
                    'vendor_id': vendor_id
                }))
                
        except Exception as e:
            logger.error(f"Error handling enhanced print jobs request: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error getting print jobs: {str(e)}'
            }))

    async def handle_job_completed(self, data):
        """Handle job completion notification with enhanced R2 updates"""
        try:
            filename = data.get('filename')
            vendor_id = data.get('vendor_id')
            user_email = data.get('user_email', '')
            completion_time = data.get('completion_time')
            r2_folder_structure = data.get('r2_folder_structure', {})
            
            logger.info(f"Enhanced job completion: {filename} by vendor {vendor_id}")
            
            # Update job status in R2 storage with enhanced validation
            await self.update_enhanced_job_status(
                filename, 'YES', vendor_id, user_email, r2_folder_structure
            )
            
            # Send confirmation
            await self.send(text_data=json.dumps({
                'type': 'job_status_updated',
                'filename': filename,
                'status': 'completed',
                'vendor_id': vendor_id,
                'timestamp': completion_time
            }))
            
            # Notify vendor dashboard if needed
            await self.notify_vendor_dashboard(vendor_id, {
                'type': 'job_completed',
                'filename': filename,
                'user_email': user_email,
                'completion_time': completion_time
            })
            
        except Exception as e:
            logger.error(f"Error handling enhanced job completion: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error updating job completion: {str(e)}'
            }))

    async def handle_job_failed(self, data):
        """Handle job failure notification with enhanced tracking"""
        try:
            filename = data.get('filename')
            vendor_id = data.get('vendor_id')
            error_message = data.get('error_message')
            user_email = data.get('user_email', '')
            failure_time = data.get('failure_time')
            
            logger.warning(f"Enhanced job failure: {filename} by vendor {vendor_id} - {error_message}")
            
            # Update failure tracking
            await self.track_enhanced_job_failure(filename, vendor_id, error_message, user_email)
            
            # Send acknowledgment
            await self.send(text_data=json.dumps({
                'type': 'job_status_updated',
                'filename': filename,
                'status': 'failed',
                'vendor_id': vendor_id,
                'error_message': error_message,
                'timestamp': failure_time
            }))
            
        except Exception as e:
            logger.error(f"Error handling enhanced job failure: {e}")

    async def handle_status_update(self, data):
        """Handle vendor client status updates"""
        try:
            vendor_id = data.get('vendor_id')
            status = data.get('status')
            details = data.get('details', {})
            
            logger.info(f"Enhanced status update from vendor {vendor_id}: {status}")
            
            # Process status update
            await self.process_enhanced_vendor_status(vendor_id, status, details)
            
        except Exception as e:
            logger.error(f"Error handling enhanced status update: {e}")

    async def handle_printer_status(self, data):
        """Handle printer status updates from vendor client"""
        try:
            vendor_id = data.get('vendor_id')
            printer_stats = data.get('printer_stats', {})
            
            logger.info(f"Enhanced printer status from vendor {vendor_id}: {printer_stats}")
            
            # Update printer status tracking
            await self.update_enhanced_printer_status(vendor_id, printer_stats)
            
        except Exception as e:
            logger.error(f"Error handling enhanced printer status: {e}")

    def validate_job_r2_structure(self, job, r2_folder_structure):
        """Validate job R2 folder structure"""
        try:
            # Use r2_path for validation if available, otherwise fall back to download_url
            r2_path = job.get('r2_path', job.get('download_url', ''))
            
            # Expected structure: users/{email}/{filename}
            # or printme/testshop/{shop_info}/{filename}
            # or printme/signupdetails/{signup_info}
            
            base_bucket = r2_folder_structure.get('base_bucket', 'printme')
            allowed_folders = r2_folder_structure.get('allowed_folders', ['signupdetails', 'testshop', 'users'])
            
            if not r2_path.startswith(base_bucket):
                return False
            
            url_parts = r2_path.split('/')
            if len(url_parts) < 2:
                return False
            
            folder_name = url_parts[1]
            if folder_name not in allowed_folders:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating R2 structure: {e}")
            return False

    @database_sync_to_async
    def get_enhanced_pending_jobs(self, vendor_id, r2_folder_structure):
        """Get pending print jobs with enhanced R2 validation"""
        try:
            # Get jobs with status 'no' (pending)
            pending_jobs = views.get_pending_print_jobs()
            
            # Filter jobs based on R2 folder structure
            validated_jobs = []
            for job in pending_jobs:
                if self.validate_job_r2_structure(job, r2_folder_structure):
                    validated_jobs.append(job)
            
            return validated_jobs
            
        except Exception as e:
            logger.error(f"Error getting enhanced pending jobs: {e}")
            return []

    @database_sync_to_async
    def update_enhanced_job_status(self, filename, status, vendor_id, user_email, r2_folder_structure):
        """Update job status in R2 storage with enhanced validation"""
        try:
            # Update job status with proper R2 folder structure
            views.update_job_status_in_r2(
                filename=filename,
                status=status,
                vendor_id=vendor_id,
                user_email=user_email,
                r2_folder_structure=r2_folder_structure
            )
            
            logger.info(f"Enhanced job status updated: {filename} -> {status}")
            
        except Exception as e:
            logger.error(f"Error updating enhanced job status: {e}")
            raise

    @database_sync_to_async
    def track_enhanced_job_failure(self, filename, vendor_id, error_message, user_email):
        """Track job failures with enhanced logging"""
        try:
            # Track failure in system
            views.track_job_failure(
                filename=filename,
                vendor_id=vendor_id,
                error_message=error_message,
                user_email=user_email
            )
            
        except Exception as e:
            logger.error(f"Error tracking enhanced job failure: {e}")

    @database_sync_to_async
    def process_enhanced_vendor_status(self, vendor_id, status, details):
        """Process vendor status updates with enhanced tracking"""
        try:
            # Update vendor status in system
            views.update_vendor_status(
                vendor_id=vendor_id,
                status=status,
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error processing enhanced vendor status: {e}")

    @database_sync_to_async
    def update_enhanced_printer_status(self, vendor_id, printer_stats):
        """Update printer status with enhanced tracking"""
        try:
            # Update printer status in system
            views.update_printer_status(
                vendor_id=vendor_id,
                printer_stats=printer_stats
            )
            
        except Exception as e:
            logger.error(f"Error updating enhanced printer status: {e}")

    async def notify_vendor_dashboard(self, vendor_id, notification_data):
        """Notify vendor dashboard of events"""
        try:
            # Send notification to vendor dashboard group
            dashboard_group = f'vendor_dashboard_{vendor_id}'
            await self.channel_layer.group_send(
                dashboard_group,
                {
                    'type': 'dashboard_notification',
                    'data': notification_data
                }
            )
            
        except Exception as e:
            logger.error(f"Error notifying vendor dashboard: {e}")

    # WebSocket event handlers for group messages
    async def dashboard_notification(self, event):
        """Handle dashboard notification events"""
        await self.send(text_data=json.dumps({
            'type': 'dashboard_notification',
            'data': event['data']
        }))

    async def print_job_request(self, event):
        """Handle print job request events"""
        await self.send(text_data=json.dumps({
            'type': 'print_job_request',
            'job': event['job']
        }))

    async def priority_job_request(self, event):
        """Handle priority print job request events"""
        await self.send(text_data=json.dumps({
            'type': 'priority_job',
            'job': event['job']
        }))
