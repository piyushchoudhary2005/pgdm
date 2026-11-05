from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from decimal import Decimal
from django.db.models import Count, F, Sum
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView, exception_handler

from .access import CUSTOMER_SCOPE, role, scope
from .audit import log_audit, dump
from .models import Customer, Lead, Opportunity, FollowUp
from .serializers import *


class ScopedViewSet(viewsets.ModelViewSet):
    owner_field = 'assigned_to'
    entity = ''
    def get_queryset(self):
        return scope(self.request.user, super().get_queryset(), self.owner_field)
    def perform_create(self, serializer):
        m = serializer.Meta.model
        extra = {}
        if hasattr(m, 'created_by'): extra['created_by'] = self.request.user
        if hasattr(m, 'assigned_to'): extra['assigned_to'] = self.request.user
        obj = serializer.save(**extra)
        log_audit(self.request, 'Create', self.entity, obj.pk, None, dump(obj))
    def perform_update(self, serializer):
        old = dump(serializer.instance)
        obj = serializer.save()
        log_audit(self.request, 'Update', self.entity, obj.pk, old, dump(obj))
    def check_delete(self):
        if role(self.request.user) not in ('Admin', 'Manager'): raise PermissionDenied('Not allowed.')
    def perform_destroy(self, instance):
        self.check_delete()
        log_audit(self.request, 'Delete', self.entity, instance.pk, dump(instance), None)
        instance.delete()

class CustomerViewSet(ScopedViewSet):
    queryset = Customer.objects.all(); serializer_class = CustomerSerializer
    owner_field = CUSTOMER_SCOPE; entity = 'Customer'
    def perform_destroy(self, instance):          # DELETE = deactivate
        self.check_delete()
        old = dump(instance); instance.status = 'Inactive'; instance.save()
        log_audit(self.request, 'Deactivate', 'Customer', instance.pk, old, dump(instance))

class LeadViewSet(ScopedViewSet):
    queryset = Lead.objects.all(); serializer_class = LeadSerializer; entity = 'Lead'

class OpportunityViewSet(ScopedViewSet):
    queryset = Opportunity.objects.all(); serializer_class = OpportunitySerializer; entity = 'Opportunity'

class FollowUpViewSet(ScopedViewSet):
    queryset = FollowUp.objects.all(); serializer_class = FollowUpSerializer; entity = 'Follow-Up'


def err(message, code):
    return Response({'status': code, 'errors': {'detail': message}}, status=code)


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        code = response.status_code
        if code == 400 and 'already exists' in str(response.data):
            code = 409
        response.data = {'status': code, 'errors': response.data}
        response.status_code = code
    return response


class ApiLogin(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        if not username or not password:
            return err('Username and password are required.', 400)
        try:
            user = authenticate(
                request=request._request,
                username=username,
                password=password,
            )
        except DjangoPermissionDenied:
            return err('Account locked. Try again later.', 403)
        if user is None:
            return err('Invalid credentials.', 401)
        login(request._request, user)
        return Response({'username': user.username, 'role': role(user)})


class ApiLogout(APIView):
    def post(self, request):
        logout(request._request)
        return Response({'detail': 'Logged out.'})


class PipelineReport(APIView):
    def get(self, request):
        opportunities = scope(
            request.user,
            Opportunity.objects.all(),
            'assigned_to',
        )
        data = (
            opportunities.values('stage', 'assigned_to__username')
            .annotate(
                count=Count('id'),
                total_amount=Sum('amount'),
                weighted_numerator=Sum(F('amount') * F('probability')),
            )
        )
        return Response([
            {
                'stage': row['stage'],
                'owner': row['assigned_to__username'],
                'count': row['count'],
                'amount': row['total_amount'],
                'weighted': (
                    row['weighted_numerator'] / Decimal('100')
                    if row['weighted_numerator'] is not None
                    else Decimal('0')
                ),
            }
            for row in data
        ])