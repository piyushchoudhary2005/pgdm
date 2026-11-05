

# Create your views here.
import json
from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from axes.models import AccessAttempt
from django.conf import settings

from .access import CUSTOMER_SCOPE, role, scope, require_role, RoleRequiredMixin
from .audit import log_audit, dump
from .forms import *
from .models import Activity, AuditLog, Customer, FollowUp, Lead, Opportunity


def make_crud(slug, mdl, form, entity, owner_field, search_fields, columns, date_field=None):
    list_url = reverse_lazy(f'{slug}_list')

    class Scoped(LoginRequiredMixin):
        def get_queryset(self):
            return scope(self.request.user, mdl.objects.all(), owner_field)
        def get_context_data(self, **kw):
            ctx = super().get_context_data(**kw)
            ctx.update(title=entity, slug=slug, list_url=list_url, create_url=reverse(f'{slug}_create'))
            return ctx

    class List(Scoped, ListView):
        template_name = 'crm/list.html'
        paginate_by = 10
        def get_queryset(self):
            qs = super().get_queryset()
            g = self.request.GET
            q = g.get('q', '').strip()
            if q:
                cond = Q()
                for f in search_fields: cond |= Q(**{f'{f}__icontains': q})
                qs = qs.filter(cond)
            if g.get('status') and hasattr(mdl, 'status'): qs = qs.filter(status=g['status'])
            if g.get('date') and date_field: qs = qs.filter(**{date_field: g['date']})
            return qs.order_by('-pk')
        def get_context_data(self, **kw):
            ctx = super().get_context_data(**kw)
            ctx['columns'] = [c.replace('_', ' ').title() for c in columns]
            ctx['rows'] = [{'cells': [getattr(o, c) for c in columns],
                            'detail': reverse(f'{slug}_detail', args=[o.pk]),
                            'edit': reverse(f'{slug}_edit', args=[o.pk]),
                            'delete': reverse(f'{slug}_delete', args=[o.pk])} for o in ctx['page_obj']]
            return ctx

    class Save(Scoped):
        form_class = form
        template_name = 'crm/form.html'
        success_url = list_url
        def get_form_kwargs(self):
            kw = super().get_form_kwargs(); kw['user'] = self.request.user; return kw
        def form_valid(self, form):
            inst = form.instance
            old = dump(mdl.objects.get(pk=inst.pk)) if inst.pk else None
            if not inst.pk:
                if hasattr(inst, 'created_by_id'): inst.created_by = self.request.user
                if hasattr(inst, 'assigned_to_id') and not inst.assigned_to_id: inst.assigned_to = self.request.user
            resp = super().form_valid(form)
            action = 'Update' if old else 'Create'
            if old and mdl is FollowUp and json.loads(old)['follow_up_date'] != str(self.object.follow_up_date):
                action = 'Reschedule'
            log_audit(self.request, action, entity, self.object.pk, old, dump(self.object))
            messages.success(self.request, f'{entity} saved.')
            return resp

    class Create(Save, CreateView): pass
    class Update(Save, UpdateView): pass

    class Detail(Scoped, DetailView):
        template_name = 'crm/detail.html'
        def get_context_data(self, **kw):
            ctx = super().get_context_data(**kw)
            ctx['fields'] = [(f.verbose_name.title(), getattr(self.object, f.name)) for f in mdl._meta.fields]
            ctx['edit_url'] = reverse(f'{slug}_edit', args=[self.object.pk])
            related = []
            if mdl is Customer:
                related = [
                    ('Opportunities', Opportunity.objects.filter(customer=self.object)),
                    ('Follow-Ups', FollowUp.objects.filter(customer=self.object)),
                    ('Activities', Activity.objects.filter(customer=self.object)),
                ]
            elif mdl is Lead:
                related = [
                    ('Opportunities', Opportunity.objects.filter(lead=self.object)),
                    ('Follow-Ups', FollowUp.objects.filter(lead=self.object)),
                    ('Activities', Activity.objects.filter(lead=self.object)),
                ]
            ctx['related'] = related
            ctx['history'] = AuditLog.objects.filter(
                entity_name=entity, record_id=str(self.object.pk)
            ).select_related('user')[:20]
            return ctx

    class Delete(RoleRequiredMixin, Scoped, DeleteView):
        allowed_roles = ('Admin', 'Manager')
        template_name = 'crm/confirm_delete.html'
        success_url = list_url
        def form_valid(self, form):
            log_audit(self.request, 'Delete', entity, self.object.pk, dump(self.object), None)
            messages.success(self.request, f'{entity} deleted.')
            return super().form_valid(form)

    return [
        path(f'{slug}/', List.as_view(), name=f'{slug}_list'),
        path(f'{slug}/create/', Create.as_view(), name=f'{slug}_create'),
        path(f'{slug}/<int:pk>/', Detail.as_view(), name=f'{slug}_detail'),
        path(f'{slug}/<int:pk>/edit/', Update.as_view(), name=f'{slug}_edit'),
        path(f'{slug}/<int:pk>/delete/', Delete.as_view(), name=f'{slug}_delete'),
    ]

crud_urls = (
    make_crud('customers', Customer, CustomerForm, 'Customer', CUSTOMER_SCOPE,
              ['customer_name', 'email', 'phone', 'company_name'],
              ['customer_code', 'customer_name', 'email', 'phone', 'company_name', 'status']) +
    make_crud('leads', Lead, LeadForm, 'Lead', 'assigned_to',
              ['lead_name', 'company_name', 'assigned_to__username'],
              ['lead_code', 'lead_name', 'company_name', 'source', 'status', 'assigned_to']) +
    make_crud('opportunities', Opportunity, OpportunityForm, 'Opportunity', 'assigned_to',
              ['opportunity_name', 'customer__customer_name', 'stage'],
              ['opportunity_name', 'customer', 'amount', 'stage', 'probability', 'expected_close_date', 'status']) +
    make_crud('followups', FollowUp, FollowUpForm, 'Follow-Up', 'assigned_to',
              ['customer__customer_name', 'lead__lead_name', 'remarks', 'assigned_to__username'],
              ['customer', 'lead', 'follow_up_date', 'follow_up_type', 'status', 'assigned_to'],
              date_field='follow_up_date') +
    make_crud('activities', Activity, ActivityForm, 'Activity', 'assigned_to',
              ['subject', 'activity_type', 'customer__customer_name', 'lead__lead_name'],
              ['activity_type', 'subject', 'activity_date', 'customer', 'lead', 'status'],
              date_field='activity_date')
)



@login_required
@require_POST
@transaction.atomic
def convert_lead(request, pk):
    lead = get_object_or_404(scope(request.user, Lead.objects.all(), 'assigned_to'), pk=pk)
    if lead.status != 'Qualified':
        messages.error(request, 'Only Qualified leads can be converted.')
        return redirect('leads_detail', pk=pk)
    customer = Customer.objects.filter(Q(email=lead.email) | Q(phone=lead.phone)).first()
    if not customer:
        customer = Customer.objects.create(customer_name=lead.lead_name, email=lead.email, phone=lead.phone,
                                           company_name=lead.company_name, created_by=request.user)
    opp = Opportunity.objects.create(
        opportunity_name=f'{lead.lead_name} - Opportunity', customer=customer, lead=lead,
        amount=max(lead.expected_value or 0, 1), stage='Qualification', probability=20,
        expected_close_date=timezone.localdate() + timedelta(days=30),
        assigned_to=lead.assigned_to or request.user)
    lead.status = 'Converted'; lead.save()
    log_audit(request, 'Convert', 'Lead', lead.pk, 'Qualified', f'Converted: customer {customer.pk}, opportunity {opp.pk}')
    messages.success(request, 'Lead converted to customer and opportunity.')
    return redirect('opportunities_detail', pk=opp.pk)

@login_required
@require_POST
def complete_followup(request, pk):
    f = get_object_or_404(scope(request.user, FollowUp.objects.all(), 'assigned_to'), pk=pk)
    old = f.status; f.status = 'Completed'; f.save()
    log_audit(request, 'Complete', 'Follow-Up', f.pk, old, 'Completed')
    messages.success(request, 'Follow-up completed.')
    return redirect('followups_list')



def register(request):
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.groups.add(Group.objects.get(name='SalesExecutive'))
        log_audit(request, 'Register', 'User', user.pk, None, user.username, user=user)
        messages.success(request, 'Registered. Please log in.')
        return redirect('login')
    return render(request, 'crm/form.html', {'form': form, 'title': 'Register', 'list_url': reverse('login')})

@login_required
def user_list(request):
    require_role(request, 'Admin')
    q = request.GET.get('q', '')
    users = User.objects.filter(username__icontains=q).order_by('username')
    rows = [(u, role(u), AccessAttempt.objects.filter(
             username=u.username, failures_since_start__gte=settings.AXES_FAILURE_LIMIT).exists()) for u in users]
    return render(request, 'crm/users.html', {'rows': rows, 'q': q})

@login_required
def user_edit(request, pk):
    require_role(request, 'Admin')
    u = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, initial={'role': role(u), 'is_active': u.is_active})
    if request.method == 'POST' and form.is_valid():
        old = f'{role(u)}, active={u.is_active}'
        u.groups.set([Group.objects.get(name=form.cleaned_data['role'])])
        u.is_active = form.cleaned_data['is_active']; u.save()
        if form.cleaned_data['unlock']:
            from axes.utils import reset
            reset(username=u.username)
        log_audit(request, 'RoleChange', 'User', u.pk, old, f"{form.cleaned_data['role']}, active={u.is_active}")
        messages.success(request, 'User updated.')
        return redirect('users')
    return render(request, 'crm/form.html', {'form': form, 'title': f'Edit {u.username}', 'list_url': reverse('users')})

@login_required
def audit_list(request):
    require_role(request, 'Admin', 'Manager')
    qs = AuditLog.objects.select_related('user')
    if role(request.user) == 'Manager':
        qs = qs.exclude(entity_name='User')
    for param, lookup in [('user', 'user__username__icontains'), ('entity', 'entity_name__icontains'),
                          ('action', 'action__icontains'), ('from', 'created_date__date__gte'),
                          ('to', 'created_date__date__lte')]:
        if request.GET.get(param): qs = qs.filter(**{lookup: request.GET[param]})
    page = Paginator(qs, 20).get_page(request.GET.get('page'))
    return render(request, 'crm/audit.html', {'page': page})