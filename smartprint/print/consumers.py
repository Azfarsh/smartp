import json
from channels.generic.websocket import AsyncWebsocketConsumer

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

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'request_print_jobs':
                # Handle print job request
                vendor_id = data.get('vendor_id')
                # Here you would typically query your database for pending print jobs
                # For now, we'll just acknowledge the request
                await self.send(text_data=json.dumps({
                    'type': 'print_jobs_response',
                    'message': 'No pending print jobs'
                }))

            elif message_type == 'print_status':
                # Handle print status updates
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'print_status_update',
                        'message': data
                    }
                )

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def print_status_update(self, event):
        # Send print status update to WebSocket
        await self.send(text_data=json.dumps(event['message']))