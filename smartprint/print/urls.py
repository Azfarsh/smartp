from django.urls import path
from . import views
from .views import (
    home,
    userdashboard,
    vendordashboard,
    upload_to_r2,
    get_print_requests,
    process_print_request
)

urlpatterns = [
    path('', home, name='home'),
    path('upload/', upload_to_r2, name='upload_to_r2'),
    path('userdashboard/', userdashboard, name='userdashboard'),
    path('vendordashboard/', vendordashboard, name='vendordashboard'),
    path('get-print-requests/', get_print_requests, name='get-print-requests'),
    path('process_print/', process_print_request, name='process_print'),  # ✅ handles 'Proceed to Print'
]
