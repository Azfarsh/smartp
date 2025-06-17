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
    path('', views.home, name='home'),
    path('upload/', views.upload_to_r2, name='upload_to_r2'),
    path('userdashboard/', views.userdashboard, name='userdashboard'),
    path('vendordashboard/', views.vendordashboard, name='vendordashboard'),
    path('get-print-requests/', views.get_print_requests, name='get-print-requests'),
    path('process_print/', process_print_request, name='process_print'),  # ✅ handles 'Proceed to Print'
    path('auto-print-documents/', views.auto_print_documents, name='auto-print-documents')
]
