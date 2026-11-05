

# Create your models here.
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL
phone_validator = RegexValidator(r'^[6-9]\d{9}$', 'Enter a valid phone number.')
def code(prefix): return f'{prefix}-{uuid.uuid4().hex[:8].upper()}'

class Customer(models.Model):
    STATUS = [('Active', 'Active'), ('Inactive', 'Inactive')]
    customer_code = models.CharField(max_length=20, unique=True, editable=False, blank=True)
    customer_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=100, unique=True)
    phone = models.CharField(max_length=10, unique=True, validators=[phone_validator])
    company_name = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=50, blank=True)
    state = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='Active')
    created_date = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, editable=False)
    def save(self, *a, **k):
        if not self.customer_code: self.customer_code = code('CUS')
        super().save(*a, **k)
    def __str__(self): return self.customer_name
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_customers')
    notes = models.TextField(blank=True)

class Lead(models.Model):
    STATUS = [(s, s) for s in ['New', 'Contacted', 'Qualified', 'Unqualified', 'Converted', 'Lost']]
    SOURCES = [(s, s) for s in ['Website', 'Referral', 'Call', 'Event', 'Social Media']]
    ALLOWED = {'New': ['Contacted', 'Unqualified', 'Lost'],
               'Contacted': ['Qualified', 'Unqualified', 'Lost'],
               'Qualified': ['Lost'],            # Converted only via the Convert button
               'Unqualified': ['Contacted', 'Lost'], 'Converted': [], 'Lost': []}
    lead_code = models.CharField(max_length=20, unique=True, editable=False, blank=True)
    lead_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=100)
    phone = models.CharField(max_length=10, validators=[phone_validator])
    company_name = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=30, choices=SOURCES)
    status = models.CharField(max_length=20, choices=STATUS, default='New')
    expected_value = models.DecimalField(max_digits=12, decimal_places=2,
                       validators=[MinValueValidator(0), MaxValueValidator(100000000)])
    created_date = models.DateTimeField(auto_now_add=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    def save(self, *a, **k):
        if not self.lead_code: self.lead_code = code('LEAD')
        super().save(*a, **k)
    PRIORITY = [(p, p) for p in ['Low', 'Medium', 'High']]
    priority = models.CharField(max_length=10, choices=PRIORITY, default='Medium')
    notes = models.TextField(blank=True)
    def clean(self):
        if self.pk:
            old = Lead.objects.filter(pk=self.pk).values_list('status', flat=True).first()
            if old and self.status != old and self.status not in self.ALLOWED.get(old, []):
                raise ValidationError({'status': f'Cannot change status from {old} to {self.status}.'})
    def __str__(self): return self.lead_name

class Opportunity(models.Model):
    STAGES = [(s, s) for s in ['Qualification', 'Proposal', 'Negotiation', 'Won', 'Lost']]
    opportunity_name = models.CharField(max_length=100)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    stage = models.CharField(max_length=20, choices=STAGES, default='Qualification')
    probability = models.IntegerField(default=10)
    expected_close_date = models.DateField()
    status = models.CharField(max_length=10, default='Open', editable=False)
    created_date = models.DateTimeField(auto_now_add=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors['amount'] = 'Opportunity Amount must be greater than 0.'
        if self.probability is not None and not (0 <= self.probability <= 100):
            errors['probability'] = 'Probability must be between 0 and 100.'
        d = self.expected_close_date
        if d and self.stage not in ('Won', 'Lost') and d < timezone.localdate():
            old = Opportunity.objects.filter(pk=self.pk).values_list('expected_close_date', flat=True).first() if self.pk else None
            if d != old:
                errors['expected_close_date'] = 'Expected Close Date cannot be in the past.'
        if errors: raise ValidationError(errors)
    def save(self, *a, **k):
        self.status = self.stage if self.stage in ('Won', 'Lost') else 'Open'
        super().save(*a, **k)
    def __str__(self): return self.opportunity_name
    source = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

class FollowUp(models.Model):
    TYPES = [(s, s) for s in ['Call', 'Meeting', 'Email', 'Visit']]
    STATUS = [(s, s) for s in ['Planned', 'Completed', 'Missed', 'Cancelled']]
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True)
    follow_up_date = models.DateField()
    follow_up_type = models.CharField(max_length=20, choices=TYPES)
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='Planned')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    def clean(self):
        errors = {}
        if not self.customer_id and not self.lead_id:
            errors['__all__'] = 'Select a customer or a lead.'
        if self.status == 'Planned' and self.follow_up_date:
            old = FollowUp.objects.filter(pk=self.pk).values_list('follow_up_date', flat=True).first() if self.pk else None
            if self.follow_up_date != old and self.follow_up_date < timezone.localdate():
                errors['follow_up_date'] = 'Follow-up date cannot be earlier than today.'
        if errors: raise ValidationError(errors)
    subject = models.CharField(max_length=150, default='Follow-up')
    def __str__(self): return f'{self.follow_up_type} on {self.follow_up_date}: {self.subject}'    

class Activity(models.Model):
    TYPES = [(s, s) for s in ['Call', 'Meeting', 'Email', 'Task']]
    STATUS = [(s, s) for s in ['Planned', 'Completed', 'Cancelled']]
    activity_type = models.CharField(max_length=20, choices=TYPES)
    subject = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    activity_date = models.DateField()
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='Planned')
    def __str__(self): return f'{self.activity_type}: {self.subject}'
class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50)
    entity_name = models.CharField(max_length=50)
    record_id = models.CharField(max_length=50, blank=True)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    class Meta: ordering = ['-created_date']
    def save(self, *a, **k):
        if self.pk: raise PermissionError('Audit records are append-only.')
        super().save(*a, **k)
    def delete(self, *a, **k): raise PermissionError('Audit records cannot be deleted.')
    