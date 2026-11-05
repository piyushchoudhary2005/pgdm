from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import CUSTOMER_SCOPE, ROLES, require_role, role, scope
from .audit import log_audit
from .forms import AdminUserForm
from .models import Activity, AuditLog, Customer, FollowUp, Lead, Opportunity


DASHBOARD_RANGES = [
    ('all', 'All time'),
    ('today', 'Today'),
    ('week', 'This Week'),
    ('month', 'This Month'),
    ('custom', 'Custom Range'),
]


def date_range(request):
    today = timezone.localdate()
    selected_range = request.GET.get('range', 'all')
    if selected_range == 'today':
        return today, today
    if selected_range == 'week':
        return today - timedelta(days=today.weekday()), today
    if selected_range == 'month':
        return today.replace(day=1), today
    if selected_range == 'custom':
        try:
            start = date.fromisoformat(request.GET['from'])
            end = date.fromisoformat(request.GET['to'])
        except (KeyError, ValueError):
            return None, None
        if start <= end:
            return start, end
    return None, None


@login_required
def dashboard(request):
    user = request.user
    today = timezone.localdate()
    customers = scope(user, Customer.objects.all(), CUSTOMER_SCOPE)
    leads = scope(user, Lead.objects.all(), 'assigned_to')
    opportunities = scope(user, Opportunity.objects.all(), 'assigned_to')
    followups = scope(user, FollowUp.objects.all(), 'assigned_to')

    start, end = date_range(request)
    if start and end:
        customers = customers.filter(created_date__date__range=(start, end))
        leads = leads.filter(created_date__date__range=(start, end))
        opportunities = opportunities.filter(created_date__date__range=(start, end))
        followups = followups.filter(follow_up_date__range=(start, end))

    open_opportunities = opportunities.filter(status='Open')
    weighted_numerator = open_opportunities.aggregate(
        total=Sum(F('amount') * F('probability'))
    )['total'] or Decimal('0')
    weighted_pipeline = weighted_numerator / Decimal('100')
    cards = [
        ('Total Customers', customers.count()),
        ('Total Leads', leads.count()),
        ('Open Leads', leads.exclude(status__in=['Lost', 'Converted', 'Unqualified']).count()),
        ('Total Opportunities', opportunities.count()),
        ('Open Opportunities', open_opportunities.count()),
        ('Won Opportunities', opportunities.filter(status='Won').count()),
        ('Lost Opportunities', opportunities.filter(status='Lost').count()),
        ('Total Pipeline Value', open_opportunities.aggregate(total=Sum('amount'))['total'] or 0),
        ('Weighted Pipeline', round(weighted_pipeline, 2)),
        ('Pending Follow-Ups', followups.filter(status='Planned').count()),
    ]
    if role(user) == 'Admin':
        cards.extend([
            ('Active Users', User.objects.filter(is_active=True).count()),
            (
                'Failed Logins (24h)',
                AuditLog.objects.filter(
                    action='FailedLogin',
                    created_date__gte=timezone.now() - timedelta(days=1),
                ).count(),
            ),
        ])

    lead_statuses = [status for status, _ in Lead.STATUS]
    opportunity_stages = [stage for stage, _ in Opportunity.STAGES]
    monthly_sales = (
        opportunities.filter(stage='Won')
        .annotate(month=TruncMonth('expected_close_date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )
    charts = {
        'lead': {
            'labels': lead_statuses,
            'values': [leads.filter(status=status).count() for status in lead_statuses],
        },
        'opp': {
            'labels': opportunity_stages,
            'values': [
                opportunities.filter(stage=stage).count()
                for stage in opportunity_stages
            ],
        },
        'sales': {
            'labels': [row['month'].strftime('%b %Y') for row in monthly_sales],
            'values': [float(row['total']) for row in monthly_sales],
        },
    }
    upcoming = followups.filter(
        status='Planned', follow_up_date__gte=today
    ).order_by('follow_up_date')[:5]
    return render(request, 'crm/dashboard.html', {
        'cards': cards,
        'charts': charts,
        'upcoming': upcoming,
        'ranges': DASHBOARD_RANGES,
    })


@login_required
def pending_followups(request):
    today = timezone.localdate()
    followups = scope(
        request.user,
        FollowUp.objects.select_related('customer', 'lead', 'assigned_to'),
        'assigned_to',
    ).filter(status='Planned')
    sections = [
        ('Overdue', followups.filter(follow_up_date__lt=today).order_by('follow_up_date'), 'danger'),
        ('Upcoming', followups.filter(follow_up_date__gte=today).order_by('follow_up_date'), 'primary'),
    ]
    return render(request, 'crm/pending.html', {'sections': sections})


@login_required
def pipeline(request):
    opportunities = scope(
        request.user,
        Opportunity.objects.select_related('customer'),
        'assigned_to',
    )
    columns = []
    for stage, _ in Opportunity.STAGES:
        items = opportunities.filter(stage=stage)
        columns.append({
            'stage': stage,
            'items': items,
            'count': items.count(),
            'total': items.aggregate(total=Sum('amount'))['total'] or 0,
        })
    open_opportunities = opportunities.filter(status='Open')
    return render(request, 'crm/pipeline.html', {
        'cols': columns,
        'stages': [stage for stage, _ in Opportunity.STAGES],
        'total': open_opportunities.aggregate(total=Sum('amount'))['total'] or 0,
        'weighted': round(
            (open_opportunities.aggregate(
                total=Sum(F('amount') * F('probability'))
            )['total'] or Decimal('0')) / Decimal('100'),
            2,
        ),
    })


@login_required
@require_POST
def move_stage(request, pk):
    opportunity = get_object_or_404(
        scope(request.user, Opportunity.objects.all(), 'assigned_to'),
        pk=pk,
    )
    new_stage = request.POST.get('stage')
    if new_stage not in dict(Opportunity.STAGES):
        messages.error(request, 'Invalid stage.')
        return redirect('pipeline')

    old_stage = opportunity.stage
    opportunity.stage = new_stage
    try:
        opportunity.full_clean()
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
        return redirect('pipeline')
    opportunity.save()
    log_audit(request, 'StageChange', 'Opportunity', opportunity.pk, old_stage, new_stage)
    messages.success(request, f'Moved to {new_stage}.')
    return redirect('pipeline')


@login_required
def user_create(request):
    require_role(request, 'Admin')
    form = AdminUserForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.groups.set([Group.objects.get(name=form.cleaned_data['role'])])
        log_audit(
            request,
            'UserCreate',
            'User',
            user.pk,
            None,
            f"{user.username}, {form.cleaned_data['role']}",
        )
        messages.success(request, 'User created.')
        return redirect('users')
    return render(request, 'crm/form.html', {
        'form': form,
        'title': 'Create User',
        'list_url': reverse('users'),
    })


@login_required
def user_reset_password(request, pk):
    require_role(request, 'Admin')
    user = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_audit(request, 'PasswordReset', 'User', user.pk, None, user.username)
        messages.success(request, 'Password reset.')
        return redirect('users')
    return render(request, 'crm/form.html', {
        'form': form,
        'title': f'Reset password: {user.username}',
        'list_url': reverse('users'),
    })


PERMISSIONS = [
    ('Dashboard', 'Full', 'Team', 'Own/Assigned'),
    ('Customers', 'Full', 'Team', 'Own/Assigned'),
    ('Leads', 'Full', 'Team', 'Own/Assigned'),
    ('Follow-Ups', 'Full', 'Team', 'Own/Assigned'),
    ('Opportunities', 'Full', 'Team', 'Own/Assigned'),
    ('Activities', 'Full', 'Team', 'Own/Assigned'),
    ('User Management', 'Full', 'No', 'No'),
    ('Role Management', 'Full', 'No', 'No'),
    ('Audit Log', 'Full', 'Limited view', 'No'),
    ('REST API', 'Authorized', 'Authorized', 'Authorized'),
    ('Reports', 'All', 'Management/team', 'Own/assigned'),
]


@login_required
def roles_view(request):
    require_role(request, 'Admin')
    counts = [(name, User.objects.filter(groups__name=name).count()) for name in ROLES]
    return render(request, 'crm/roles.html', {
        'counts': counts,
        'perms': PERMISSIONS,
    })


@login_required
def global_search(request):
    query = request.GET.get('q', '').strip()
    user = request.user
    results = []
    if query:
        results = [
            (
                'Customers',
                [
                    (customer, reverse('customers_detail', args=[customer.pk]))
                    for customer in scope(
                        user, Customer.objects.all(), CUSTOMER_SCOPE
                    ).filter(
                        Q(customer_name__icontains=query)
                        | Q(email__icontains=query)
                        | Q(phone__icontains=query)
                        | Q(company_name__icontains=query)
                    )[:10]
                ],
            ),
            (
                'Leads',
                [
                    (lead, reverse('leads_detail', args=[lead.pk]))
                    for lead in scope(
                        user, Lead.objects.all(), 'assigned_to'
                    ).filter(
                        Q(lead_name__icontains=query)
                        | Q(company_name__icontains=query)
                        | Q(email__icontains=query)
                    )[:10]
                ],
            ),
            (
                'Opportunities',
                [
                    (opportunity, reverse('opportunities_detail', args=[opportunity.pk]))
                    for opportunity in scope(
                        user, Opportunity.objects.all(), 'assigned_to'
                    ).filter(opportunity_name__icontains=query)[:10]
                ],
            ),
        ]
    return render(request, 'crm/search.html', {'q': query, 'results': results})
