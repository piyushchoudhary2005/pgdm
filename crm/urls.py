from django.urls import path

from . import reports, views, views_extra as extra


urlpatterns = [
    path('', extra.dashboard, name='dashboard'),
    path('register/', views.register, name='register'),
    path('search/', extra.global_search, name='search'),
    path('pipeline/', extra.pipeline, name='pipeline'),
    path('opportunities/<int:pk>/stage/', extra.move_stage, name='move_stage'),
    path('followups/pending/', extra.pending_followups, name='pending'),
    path('leads/<int:pk>/convert/', views.convert_lead, name='convert_lead'),
    path('followups/<int:pk>/complete/', views.complete_followup, name='complete_followup'),
    path('audit/', views.audit_list, name='audit'),
    path('users/', views.user_list, name='users'),
    path('users/create/', extra.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/reset-password/', extra.user_reset_password, name='user_reset'),
    path('roles/', extra.roles_view, name='roles'),
    path('reports/', reports.reports_index, name='reports'),
    path('reports/<slug:name>/', reports.report, name='report'),
] + views.crud_urls
