from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from print.routing import websocket_urlpatterns


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('print.urls')),  # Include your app's routes
    # Favicon route to ensure proper serving
    path('favicon.ico', RedirectView.as_view(url='/static/images/favicon.ico', permanent=True)),
    # Firebase service worker route is handled in print.urls
]

# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Add WebSocket routing
application = ProtocolTypeRouter({
    "websocket": AuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})