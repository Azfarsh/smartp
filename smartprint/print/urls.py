
from django.urls import path
from . import views
from .views import (home, userdashboard, vendordashboard, upload_to_r2,
                    get_print_requests, process_print_request, auto_print_documents, update_job_status)
from .firebase_auth import firebase_auth

urlpatterns = [
    path('', views.home, name='home'),
    path('upload/', views.upload_to_r2, name='upload_to_r2'),
    path('userdashboard/', views.userdashboard, name='userdashboard'),
    path('vendordashboard/', views.vendordashboard, name='vendordashboard'),
    path('get-print-requests/',
         views.get_print_requests,
         name='get-print-requests'),
    path('process_print/', process_print_request, name='process_print'),
    path('auto-print-documents/', auto_print_documents, name='auto-print-documents'),
    path('update-job-status/', update_job_status, name='update-job-status'),
    path('login/', views.login_page, name='login'),
    path('firebase-auth/', firebase_auth, name='firebase-auth'),
]
