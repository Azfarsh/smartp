import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import PrintJob
import logging

logger = logging.getLogger(__name__)

class VendorConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Handle WebSocket connection"""
        self.vendor_id = self.scope['url_route']['kwargs']['vendor_id']
        self.room_group_name = f'vendor_{self.vendor_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"Vendor {self.vendor_id} connected")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        logger.info(f"Vendor {self.vendor_id} disconnected")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'auth':
                # Handle authentication
                token = data.get('token')
                if await self.verify_token(token):
                    await self.send(json.dumps({
                        'type': 'auth_status',
                        'status': 'success'
                    }))
                else:
                    await self.send(json.dumps({
                        'type': 'auth_status',
                        'status': 'error',
                        'message': 'Invalid token'
                    }))
            
            elif message_type == 'print_status':
                # Handle print status updates
                await self.handle_print_status(data)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def send_print_request(self, event):
        """Send print request to vendor"""
        print_job = event['print_job']
        await self.send(json.dumps({
            'type': 'print_request',
            'file_url': print_job['file_url'],
            'request_id': print_job['id']
        }))

    @database_sync_to_async
    def verify_token(self, token):
        """Verify vendor token"""
        # Add your token verification logic here
        return True  # For testing, always return True

    @database_sync_to_async
    def handle_print_status(self, data):
        """Handle print status updates"""
        try:
            print_job = PrintJob.objects.get(id=data.get('request_id'))
            print_job.status = data.get('status')
            print_job.save()
        except PrintJob.DoesNotExist:
            logger.error(f"Print job {data.get('request_id')} not found")
        except Exception as e:
            logger.error(f"Error updating print job status: {e}") 