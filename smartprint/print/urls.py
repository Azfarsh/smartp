from django.urls import path
from . import views
from .views import upload_to_r2
from .views import get_print_requests

urlpatterns = [
    path('', views.home, name='home'),              # Home page route
    path('upload/', upload_to_r2, name='upload_to_r2'),  # Upload endpoint for R2
    path('userdashboard/', views.userdashboard, name='userdashboard'),  # User dashboard route
    path('vendordashboard/', views.vendordashboard, name='vendordashboard'),  # Vendor dashboard route
      path('get-print-requests/', get_print_requests, name='get-print-requests'),
  ]
