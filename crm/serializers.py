import copy
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .access import CUSTOMER_SCOPE, scope
from .models import Customer, Lead, Opportunity, FollowUp

class CleanSerializer(serializers.ModelSerializer):
    """Runs the same model.clean() business rules the web forms use."""
    def validate(self, attrs):
        inst = copy.copy(self.instance) if self.instance else self.Meta.model()
        for k, v in attrs.items(): setattr(inst, k, v)
        try: inst.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'error_dict') else e.messages)
        return attrs

class CustomerSerializer(CleanSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'customer_code', 'customer_name', 'email', 'phone', 'company_name',
                  'address', 'city', 'state', 'status', 'created_date', 'assigned_to', 'notes']
        read_only_fields = ['id', 'customer_code', 'created_date', 'assigned_to', 'notes']

class LeadSerializer(CleanSerializer):
    class Meta:
        model = Lead
        fields = ['id', 'lead_code', 'lead_name', 'email', 'phone', 'company_name', 'source',
                  'status', 'expected_value', 'created_date', 'assigned_to', 'priority', 'notes']
        read_only_fields = ['id', 'lead_code', 'created_date', 'assigned_to']

    def validate_status(self, status):
        if self.instance is None and status != 'New':
            raise serializers.ValidationError('New leads must have status New.')
        return status

class OpportunitySerializer(CleanSerializer):
    class Meta:
        model = Opportunity
        fields = ['id', 'opportunity_name', 'customer', 'lead', 'amount', 'stage', 'probability',
                  'expected_close_date', 'status', 'created_date', 'assigned_to', 'source', 'notes']
        read_only_fields = ['id', 'status', 'created_date', 'assigned_to']
    def validate_customer(self, c):
        if not scope(
            self.context['request'].user,
            Customer.objects.all(),
            CUSTOMER_SCOPE,
        ).filter(pk=c.pk).exists():
            raise serializers.ValidationError('Invalid customer.')
        return c

    def validate_lead(self, lead):
        if lead is not None and not scope(
            self.context['request'].user,
            Lead.objects.all(),
            'assigned_to',
        ).filter(pk=lead.pk).exists():
            raise serializers.ValidationError('Invalid lead.')
        return lead

class FollowUpSerializer(CleanSerializer):
    class Meta:
        model = FollowUp
        fields = ['id', 'customer', 'lead', 'follow_up_date', 'follow_up_type',
                  'remarks', 'status', 'assigned_to', 'subject']
        read_only_fields = ['id', 'assigned_to']

    def validate_customer(self, customer):
        if customer is not None and not scope(
            self.context['request'].user,
            Customer.objects.all(),
            CUSTOMER_SCOPE,
        ).filter(pk=customer.pk).exists():
            raise serializers.ValidationError('Invalid customer.')
        return customer

    def validate_lead(self, lead):
        if lead is not None and not scope(
            self.context['request'].user,
            Lead.objects.all(),
            'assigned_to',
        ).filter(pk=lead.pk).exists():
            raise serializers.ValidationError('Invalid lead.')
        return lead