from django.urls import path
from . import views
from .views import (home, userdashboard, vendordashboard, upload_to_r2,
                    get_print_requests, process_print_request, auto_print_documents, update_job_status,
                    auth_receiver, sign_in, photoprint, vendor_register, vendor_pricing, vendor_info,
                    vendor_login, vendor_register_api)


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
    path('login/', sign_in, name='login'),
    path('auth-receiver/', auth_receiver, name='auth_receiver'),
    path('photoprint/', photoprint, name='photoprint'),
    path('vendor-register/', vendor_register, name='vendor_register'),
    path('vendor-pricing/', vendor_pricing, name='vendor_pricing'),
    path('vendor-info/<str:vendor_id>/', vendor_info, name='vendor_info'),
    path('vendor-login/', vendor_login, name='vendor_login'),
    path('vendor-register-api/', vendor_register_api, name='vendor_register_api'),
]

