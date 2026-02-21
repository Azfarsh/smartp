from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.views.generic.base import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from print.routing import websocket_urlpatterns
from print.sitemaps import StaticViewSitemap


sitemaps = {
    'static': StaticViewSitemap,
}


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('print.urls')),  # Include your app's routes
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),
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