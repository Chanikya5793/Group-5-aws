from django.urls import path

from . import views
from .csv_upload import upload_csv

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('patient/', views.patient_dashboard, name='patient_dashboard'),
    path('clinician/', views.clinician_dashboard, name='clinician_dashboard'),
    path('report/', views.patient_report, name='patient_report'),
    path('report/<int:patient_id>/', views.patient_report, name='patient_report_for'),
    path('upload/', upload_csv, name='upload_csv'),

    # API endpoints
    path('api/session/<int:session_id>/frames/', views.api_session_frames, name='api_session_frames'),
    path('api/session/<int:session_id>/latest/', views.api_latest_frame, name='api_latest_frame'),
    path('api/session/<int:session_id>/metrics/', views.api_session_metrics_timeline, name='api_session_metrics'),
    path('api/session/<int:session_id>/comments/', views.api_session_comments, name='api_session_comments'),
    path('api/session/<int:session_id>/comment/', views.api_add_comment, name='api_add_comment'),
    path('api/session/<int:session_id>/flag/', views.api_flag_session, name='api_flag_session'),
    path('api/frame/<int:frame_id>/', views.api_frame_detail, name='api_frame_detail'),
    path('api/alert/<int:alert_id>/acknowledge/', views.api_acknowledge_alert, name='api_acknowledge_alert'),
    path('api/patient/<int:patient_id>/sessions/', views.api_patient_sessions, name='api_patient_sessions'),
    path('api/comment/<int:comment_id>/reply/', views.api_reply_comment, name='api_reply_comment'),
]