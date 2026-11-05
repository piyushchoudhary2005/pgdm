from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from datetime import date
from .access import CUSTOMER_SCOPE, role, scope, ROLES
from .models import Customer, Lead, Opportunity, FollowUp, Activity


class BaseForm(forms.ModelForm):
    def __init__(self, *a, user=None, **kw):
        super().__init__(*a, **kw)
        if user:
            if 'assigned_to' in self.fields:
                self.fields['assigned_to'].queryset = User.objects.filter(
                    groups__name='SalesExecutive',
                    is_active=True,
                )
            if 'assigned_to' in self.fields and role(user) == 'SalesExecutive':
                del self.fields['assigned_to']
            if 'customer' in self.fields:
                self.fields['customer'].queryset = scope(
                    user, Customer.objects.all(), CUSTOMER_SCOPE
                )
            if 'lead' in self.fields:
                self.fields['lead'].queryset = scope(
                    user, Lead.objects.all(), 'assigned_to'
                )
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'form-control')


PHONE = {'pattern': '[6-9][0-9]{9}', 'title': '10-digit Indian mobile number', 'inputmode': 'numeric'}


def date_widget():
    return forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')

class CustomerForm(BaseForm):
    class Meta:
        model = Customer
        fields = [
            'customer_name', 'email', 'phone', 'company_name', 'address',
            'city', 'state', 'status', 'assigned_to', 'notes',
        ]
        widgets = {'phone': forms.TextInput(attrs=PHONE)}

class LeadForm(BaseForm):
    class Meta:
        model = Lead
        fields = [
            'lead_name', 'email', 'phone', 'company_name', 'source', 'status',
            'expected_value', 'assigned_to', 'priority', 'notes',
        ]
        widgets = {'phone': forms.TextInput(attrs=PHONE),
                   'expected_value': forms.NumberInput(attrs={'min': 0, 'step': '0.01'})}

class OpportunityForm(BaseForm):
    class Meta:
        model = Opportunity
        fields = [
            'opportunity_name', 'customer', 'lead', 'amount', 'stage',
            'probability', 'expected_close_date', 'assigned_to', 'source',
            'notes',
        ]
        widgets = {'expected_close_date': date_widget(),
                   'amount': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
                   'probability': forms.NumberInput(attrs={'min': 0, 'max': 100})}
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if not self.instance.pk:
            self.fields['expected_close_date'].widget.attrs['min'] = date.today().isoformat()

class FollowUpForm(BaseForm):
    class Meta:
        model = FollowUp
        fields = [
            'customer', 'lead', 'follow_up_date', 'follow_up_type',
            'remarks', 'status', 'assigned_to', 'subject',
        ]
        widgets = {'follow_up_date': date_widget(), 'remarks': forms.Textarea(attrs={'rows': 3})}
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if not self.instance.pk:
            self.fields['follow_up_date'].widget.attrs['min'] = date.today().isoformat()

class ActivityForm(BaseForm):
    class Meta:
        model = Activity
        fields = ['activity_type', 'subject', 'description', 'activity_date', 'customer', 'lead', 'status', 'assigned_to']
        widgets = {'activity_date': date_widget(), 'description': forms.Textarea(attrs={'rows': 3})}

class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    class Meta(UserCreationForm.Meta):
        fields = ('username', 'email')
    def clean_email(self):
        e = self.cleaned_data['email']
        if User.objects.filter(email__iexact=e).exists(): raise forms.ValidationError('Email already registered.')
        return e

class UserEditForm(forms.Form):
    role = forms.ChoiceField(choices=[(r, r) for r in ROLES])
    is_active = forms.BooleanField(required=False)
    unlock = forms.BooleanField(required=False, label='Unlock account')


class AdminUserForm(RegisterForm):
    role = forms.ChoiceField(choices=[(r, r) for r in ROLES])