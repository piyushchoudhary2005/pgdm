from django.contrib.auth.decorators import login_required
from django.urls import path, re_path
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter
from . import api_views as v

router = DefaultRouter(trailing_slash=False)
# DRF takes a boolean here; its generated regex accepts an optional final slash.
router.trailing_slash = '/?'
router.register('customers', v.CustomerViewSet)
router.register('leads', v.LeadViewSet)
router.register('opportunities', v.OpportunityViewSet)
router.register('followups', v.FollowUpViewSet)

urlpatterns = [
    re_path(r'^auth/login/?$', v.ApiLogin.as_view(), name='api_login'),
    re_path(r'^auth/logout/?$', v.ApiLogout.as_view(), name='api_logout'),
    re_path(r'^reports/pipeline/?$', v.PipelineReport.as_view(), name='api_pipeline'),
    path(
        'docs/',
        login_required(TemplateView.as_view(template_name='crm/api_docs.html')),
        name='api_docs',
    ),
] + router.urls