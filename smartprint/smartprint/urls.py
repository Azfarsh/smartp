from django.contrib import admin
from django.urls import path, include
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from print.routing import websocket_urlpatterns
from django.conf.urls import handler404

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('print.urls')),  # Include your app's routes
]

# Custom 404 handler
def custom_404_view(request, exception):
    from django.shortcuts import render
    return render(request, '404.html', status=404)

handler404 = custom_404_view

# Add WebSocket routing
application = ProtocolTypeRouter({
    "websocket": AuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})