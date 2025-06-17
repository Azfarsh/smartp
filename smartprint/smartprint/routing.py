from django.urls import re_path
from vendor.consumers import VendorConsumer

websocket_urlpatterns = [
    re_path(r'^ws/vendor/print/(?P<vendor_id>\w+)/$', VendorConsumer.as_asgi()),
] 