
import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.http import JsonResponse
from . import views

class VendorConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.vendor_id = self.scope['url_route']['kwargs']['vendor_id']
        self.room_group_name = f'vendor_{self.vendor_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        print(f"✅ Vendor {self.vendor_id} connected successfully")
        
        # Send welcome message
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': f'Connected as vendor {self.vendor_id}',
            'vendor_id': self.vendor_id
        }))
        
        # Automatically send pending jobs when vendor connects
        await asyncio.sleep(1)  # Small delay to ensure connection is stable
        await self.send_pending_jobs()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        print(f"Vendor {self.vendor_id} disconnected")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'request_print_jobs':
                # Get pending print jobs and send them to client
                await self.send_pending_jobs()

            elif message_type == 'job_completed':
                # Handle job completion notification from client
                await self.handle_job_completion(data)

            elif message_type == 'job_failed':
                # Handle job failure notification from client
                await self.handle_job_failure(data)

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def send_pending_jobs(self):
        """Get pending print jobs and send them to the client one by one"""
        try:
            # Get pending jobs from database/storage
            pending_jobs = await database_sync_to_async(views.get_pending_print_jobs)()
            
            if not pending_jobs:
                await self.send(text_data=json.dumps({
                    'type': 'print_jobs_response',
                    'message': 'No pending print jobs',
                    'jobs': []
                }))
                return
            
            # Send jobs one by one with a small delay
            for job in pending_jobs:
                await self.send(text_data=json.dumps({
                    'type': 'print_job',
                    'job': {
                        'filename': job['filename'],
                        'download_url': job['download_url'],
                        'metadata': job['metadata']
                    }
                }))
                
                # Small delay between jobs to prevent overwhelming the client
                await asyncio.sleep(0.5)
            
            print(f"Sent {len(pending_jobs)} print jobs to vendor {self.vendor_id}")
            
        except Exception as e:
            print(f"Error sending pending jobs: {str(e)}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error getting print jobs: {str(e)}'
            }))

    async def handle_job_completion(self, data):
        """Handle job completion notification from client"""
        try:
            filename = data.get('filename')
            if not filename:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Filename required for job completion'
                }))
                return
            
            # Update job status in storage
            success = await database_sync_to_async(views.update_file_job_status)(filename, 'YES')
            
            if success:
                await self.send(text_data=json.dumps({
                    'type': 'job_status_updated',
                    'filename': filename,
                    'status': 'completed',
                    'message': f'Job completed successfully for {filename}'
                }))
                print(f"Job completed for {filename} by vendor {self.vendor_id}")
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Failed to update job status for {filename}'
                }))
                
        except Exception as e:
            print(f"Error handling job completion: {str(e)}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error updating job status: {str(e)}'
            }))

    async def handle_job_failure(self, data):
        """Handle job failure notification from client"""
        try:
            filename = data.get('filename')
            error_message = data.get('error_message', 'Unknown error')
            
            if not filename:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Filename required for job failure'
                }))
                return
            
            # Update job status to failed
            success = await database_sync_to_async(views.update_file_job_status)(filename, 'FAILED')
            
            if success:
                await self.send(text_data=json.dumps({
                    'type': 'job_status_updated',
                    'filename': filename,
                    'status': 'failed',
                    'message': f'Job failed for {filename}: {error_message}'
                }))
                print(f"Job failed for {filename} by vendor {self.vendor_id}: {error_message}")
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Failed to update job status for {filename}'
                }))
                
        except Exception as e:
            print(f"Error handling job failure: {str(e)}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error updating job status: {str(e)}'
            }))

    async def print_status_update(self, event):
        # Send print status update to WebSocket
        await self.send(text_data=json.dumps(event['message']))
