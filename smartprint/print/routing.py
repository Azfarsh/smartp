from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/vendor/(?P<vendor_id>\w+)/$', consumers.VendorConsumer.as_asgi()),
]