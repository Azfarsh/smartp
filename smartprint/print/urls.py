from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),              # Home page route
    path('upload/', views.upload_to_r2, name='upload_to_r2'),  # Upload endpoint for R2
    path('userdashboard/', views.userdashboard, name='userdashboard'),  # User dashboard route
    path('vendordashboard/', views.vendordashboard, name='vendordashboard'),  # Vendor dashboard route
    path('get-print-requests/', views.get_print_requests, name='get-print-requests'),
    path('auto-print-documents/', views.auto_print_documents, name='auto-print-documents'),  # Auto print endpoint
]
