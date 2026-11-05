import csv
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, F, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .access import CUSTOMER_SCOPE, role, scope
from .audit import log_audit
from .models import AuditLog, Customer, FollowUp, Lead, Opportunity


ALL_ROLES = ('Admin', 'Manager', 'SalesExecutive')
MANAGER_ROLES = ('Admin', 'Manager')
REPORTS = {
    'customers': ('Customer Report', ALL_ROLES, ['status']),
    'leads': ('Lead Report', ALL_ROLES, ['status']),
    'followups': ('Follow-Up Report', ALL_ROLES, ['status']),
    'opportunities': ('Opportunity Report', ALL_ROLES, ['stage']),
    'pipeline': ('Pipeline Report', ALL_ROLES, []),
    'conversion': ('Sales / Conversion Report', ALL_ROLES, []),
    'user-activity': ('User Activity Report', MANAGER_ROLES, ['user']),
    'audit': ('Audit Report', MANAGER_ROLES, ['user', 'entity', 'action']),
}
def _sort_key(value):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _safe_csv_value(value):
    text = '' if value is None else str(value)
    if text.startswith(('=', '+', '-', '@')):
        return "'" + text
    return text


def _rows(request, name):
    user, query, today = request.user, request.GET, timezone.localdate()

    def parse_date(key):
        try:
            return date.fromisoformat(query.get(key, ''))
        except ValueError:
            return None

    def date_filter(queryset, field):
        start, end = parse_date('from'), parse_date('to')
        if start:
            queryset = queryset.filter(**{f'{field}__gte': start})
        if end:
            queryset = queryset.filter(**{f'{field}__lte': end})
        return queryset

    if name == 'customers':
        queryset = date_filter(
            scope(
                user,
                Customer.objects.select_related('created_by'),
                CUSTOMER_SCOPE,
            ),
            'created_date__date',
        )
        if query.get('status'):
            queryset = queryset.filter(status=query['status'])
        return (
            ['Code', 'Name', 'Status', 'Owner', 'Created'],
            [
                [customer.customer_code, customer.customer_name, customer.status,
                 customer.created_by, customer.created_date.date()]
                for customer in queryset
            ],
        )

    if name == 'leads':
        queryset = date_filter(
            scope(
                user,
                Lead.objects.select_related('assigned_to').annotate(
                    opportunity_count=Count('opportunity')
                ),
                'assigned_to',
            ),
            'created_date__date',
        )
        if query.get('status'):
            queryset = queryset.filter(status=query['status'])
        return (
            ['Code', 'Lead', 'Source', 'Status', 'Owner', 'Converted', 'Opportunities'],
            [
                [
                    lead.lead_code, lead.lead_name, lead.source, lead.status,
                    lead.assigned_to, 'Yes' if lead.status == 'Converted' else 'No',
                    lead.opportunity_count,
                ]
                for lead in queryset
            ],
        )

    if name == 'followups':
        queryset = date_filter(
            scope(
                user,
                FollowUp.objects.select_related('customer', 'lead', 'assigned_to'),
                'assigned_to',
            ),
            'follow_up_date',
        )
        if query.get('status'):
            queryset = queryset.filter(status=query['status'])
        return (
            ['Date', 'Related', 'Subject', 'Type', 'Status', 'Owner', 'Overdue'],
            [
                [
                    followup.follow_up_date,
                    followup.customer or followup.lead,
                    followup.subject,
                    followup.follow_up_type,
                    followup.status,
                    followup.assigned_to,
                    'Yes' if followup.status == 'Planned' and followup.follow_up_date < today else 'No',
                ]
                for followup in queryset
            ],
        )

    if name == 'opportunities':
        queryset = date_filter(
            scope(
                user,
                Opportunity.objects.select_related('customer', 'assigned_to'),
                'assigned_to',
            ),
            'expected_close_date',
        )
        if query.get('stage'):
            queryset = queryset.filter(stage=query['stage'])
        return (
            ['Opportunity', 'Customer', 'Stage', 'Amount', 'Probability', 'Weighted', 'Close date', 'Owner'],
            [
                [
                    opportunity.opportunity_name,
                    opportunity.customer,
                    opportunity.stage,
                    opportunity.amount,
                    opportunity.probability,
                    opportunity.amount * opportunity.probability / 100,
                    opportunity.expected_close_date,
                    opportunity.assigned_to,
                ]
                for opportunity in queryset
            ],
        )

    if name == 'pipeline':
        queryset = date_filter(
            scope(user, Opportunity.objects.all(), 'assigned_to'),
            'created_date__date',
        )
        data = (
            queryset.values('stage', 'assigned_to__username')
            .annotate(
                count=Count('id'),
                total_amount=Sum('amount'),
                weighted_numerator=Sum(F('amount') * F('probability')),
            )
            .order_by('stage', 'assigned_to__username')
        )
        return (
            ['Stage', 'Owner', 'Count', 'Amount', 'Weighted'],
            [
                [
                    row['stage'],
                    row['assigned_to__username'] or 'Unassigned',
                    row['count'],
                    row['total_amount'],
                    row['weighted_numerator'] / Decimal('100') if row['weighted_numerator'] is not None else Decimal('0'),
                ]
                for row in data
            ],
        )

    if name == 'conversion':
        leads = date_filter(
            scope(user, Lead.objects.all(), 'assigned_to'),
            'created_date__date',
        )
        opportunities = date_filter(
            scope(user, Opportunity.objects.all(), 'assigned_to'),
            'created_date__date',
        )
        names = set(leads.values_list('assigned_to__username', flat=True))
        names.update(opportunities.values_list('assigned_to__username', flat=True))
        rows = []
        for username in sorted(names, key=lambda value: value or ''):
            user_leads = leads.filter(assigned_to__username=username)
            user_opportunities = opportunities.filter(assigned_to__username=username)
            total_leads = user_leads.count()
            converted = user_leads.filter(status='Converted').count()
            rows.append([
                username or 'Unassigned',
                total_leads,
                converted,
                total_leads - converted,
                f'{(converted * 100 / total_leads if total_leads else 0):.1f}%',
                user_opportunities.filter(status='Won').count(),
                user_opportunities.filter(status='Lost').count(),
            ])
        return (
            ['Owner', 'Leads', 'Converted', 'Not converted', 'Conversion %', 'Opps won', 'Opps lost'],
            rows,
        )

    if name == 'user-activity':
        queryset = date_filter(AuditLog.objects.all(), 'created_date__date')
        if query.get('user'):
            queryset = queryset.filter(user__username__icontains=query['user'])
        data = (
            queryset.values('user__username', 'action')
            .annotate(count=Count('id'))
            .order_by('user__username', 'action')
        )
        return (
            ['User', 'Action', 'Count'],
            [[row['user__username'] or 'Anonymous', row['action'], row['count']] for row in data],
        )

    queryset = date_filter(
        AuditLog.objects.select_related('user'),
        'created_date__date',
    )
    if role(user) == 'Manager':
        queryset = queryset.exclude(entity_name='User')
    if query.get('user'):
        queryset = queryset.filter(user__username__icontains=query['user'])
    if query.get('entity'):
        queryset = queryset.filter(entity_name__icontains=query['entity'])
    if query.get('action'):
        queryset = queryset.filter(action__icontains=query['action'])
    return (
        ['Time', 'User', 'Action', 'Entity', 'Record', 'IP'],
        [
            [
                timezone.localtime(entry.created_date).strftime('%Y-%m-%d %H:%M'),
                entry.user,
                entry.action,
                entry.entity_name,
                entry.record_id,
                entry.ip_address,
            ]
            for entry in queryset
        ],
    )


@login_required
def reports_index(request):
    items = [
        (slug, definition[0])
        for slug, definition in REPORTS.items()
        if role(request.user) in definition[1]
    ]
    return render(request, 'crm/reports.html', {'items': items})


@login_required
def report(request, name):
    if name not in REPORTS:
        raise Http404
    title, allowed_roles, filters = REPORTS[name]
    if role(request.user) not in allowed_roles:
        raise PermissionDenied

    headers, rows = _rows(request, name)
    query = request.GET
    sort = query.get('sort', '')
    if sort.isdigit() and int(sort) < len(headers):
        rows.sort(
            key=lambda row: _sort_key(row[int(sort)]),
            reverse=query.get('dir') == 'desc',
        )
    if query.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{name}.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_safe_csv_value(value) for value in row])
        log_audit(request, 'Export', 'Report', name)
        return response

    query_without_page = query.copy()
    query_without_page.pop('page', None)
    query_without_page.pop('export', None)
    query_without_sort = query_without_page.copy()
    query_without_sort.pop('sort', None)
    query_without_sort.pop('dir', None)
    header_context = [
        {
            'label': header,
            'i': index,
            'dir': 'desc' if sort == str(index) and query.get('dir') != 'desc' else 'asc',
        }
        for index, header in enumerate(headers)
    ]
    return render(request, 'crm/report.html', {
        'title': title,
        'name': name,
        'heads': header_context,
        'page': Paginator(rows, 15).get_page(query.get('page')),
        'fvals': [(field, query.get(field, '')) for field in filters],
        'q': query_without_page.urlencode(),
        'q_nosort': query_without_sort.urlencode(),
    })
