from django.test import RequestFactory, TestCase

import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser, Group, User
from django.conf import settings
from django.test import override_settings

from .forms import LeadForm
from .models import AuditLog, Customer, FollowUp, Lead, Opportunity
from .audit import get_ip
from axes.helpers import get_lockout_response


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class DashboardAndApiTests(TestCase):
    def setUp(self):
        manager_group, _ = Group.objects.get_or_create(name='Manager')
        self.admin = User.objects.create_superuser(
            username='test-admin',
            email='test-admin@example.test',
            password='Pass123!safe',
        )
        self.manager = User.objects.create_user(
            username='test-manager',
            email='test-manager@example.test',
            password='Pass123!safe',
        )
        self.manager.groups.add(manager_group)
        self.sales_user = User.objects.create_user(
            username='test-sales',
            email='test-sales@example.test',
            password='Pass123!safe',
        )
        self.other_sales_user = User.objects.create_user(
            username='other-sales',
            email='other-sales@example.test',
            password='Pass123!safe',
        )
        self.customer = Customer.objects.create(
            customer_name='Test Customer',
            email='customer@example.test',
            phone='6123456789',
            created_by=self.admin,
        )
        self.opportunity = Opportunity.objects.create(
            opportunity_name='Test Opportunity',
            customer=self.customer,
            amount=Decimal('123.00'),
            probability=50,
            expected_close_date=date.today() + timedelta(days=30),
            assigned_to=self.admin,
        )
        self.other_customer = Customer.objects.create(
            customer_name='Other Customer',
            email='other-customer@example.test',
            phone='6234567890',
            created_by=self.other_sales_user,
        )
        self.other_lead = Lead.objects.create(
            lead_name='Other Lead',
            email='other-lead@example.test',
            phone='6345678901',
            source='Website',
            expected_value=Decimal('500.00'),
            assigned_to=self.other_sales_user,
        )

    def test_dashboard_and_pipeline_report_render(self):
        self.client.force_login(self.admin)
        dashboard = self.client.get('/', HTTP_HOST='localhost')
        report = self.client.get('/reports/pipeline/', HTTP_HOST='localhost')

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(report.status_code, 200)
        self.assertContains(dashboard, 'Upcoming follow-ups')
        self.assertContains(report, 'Pipeline Report')

    def test_pipeline_api_calculates_weighted_value_without_integer_truncation(self):
        self.client.force_login(self.admin)

        response = self.client.get('/api/reports/pipeline', HTTP_HOST='localhost')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['weighted'], 61.5)

    def test_api_login_returns_authenticated_user_role(self):
        response = self.client.post(
            '/api/auth/login',
            data=json.dumps({
                'username': 'test-admin',
                'password': 'Pass123!safe',
            }),
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'username': 'test-admin', 'role': 'Admin'})

    def test_customer_api_accepts_both_slash_forms(self):
        self.client.force_login(self.admin)

        without_slash = self.client.get('/api/customers', HTTP_HOST='localhost')
        with_slash = self.client.get('/api/customers/', HTTP_HOST='localhost')

        self.assertEqual(without_slash.status_code, 200)
        self.assertEqual(with_slash.status_code, 200)

    def test_duplicate_customer_api_response_uses_conflict_status(self):
        self.client.force_login(self.admin)
        payload = {
            'customer_name': 'Duplicate Customer',
            'email': self.customer.email,
            'phone': self.customer.phone,
        }

        response = self.client.post(
            '/api/customers',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['status'], 409)
        self.assertIn('errors', response.json())

    def test_followup_api_rejects_customer_and_lead_outside_sales_scope(self):
        self.client.force_login(self.sales_user)
        payload = {
            'follow_up_date': (date.today() + timedelta(days=1)).isoformat(),
            'follow_up_type': 'Call',
        }

        customer_response = self.client.post(
            '/api/followups',
            data=json.dumps({**payload, 'customer': self.other_customer.pk}),
            content_type='application/json',
            HTTP_HOST='localhost',
        )
        lead_response = self.client.post(
            '/api/followups',
            data=json.dumps({**payload, 'lead': self.other_lead.pk}),
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(customer_response.status_code, 400)
        self.assertIn('customer', customer_response.json()['errors'])
        self.assertEqual(lead_response.status_code, 400)
        self.assertIn('lead', lead_response.json()['errors'])

    def test_opportunity_api_rejects_lead_outside_sales_scope(self):
        self.client.force_login(self.sales_user)
        payload = {
            'opportunity_name': 'Out of scope lead',
            'customer': self.customer.pk,
            'lead': self.other_lead.pk,
            'amount': '100.00',
            'stage': 'Qualification',
            'probability': 10,
            'expected_close_date': (date.today() + timedelta(days=30)).isoformat(),
        }

        response = self.client.post(
            '/api/opportunities',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('lead', response.json()['errors'])

    def test_new_lead_form_only_allows_new_status(self):
        form = LeadForm(data={
            'lead_name': 'Form Lead',
            'email': 'form-lead@example.test',
            'phone': '6456789012',
            'source': 'Website',
            'status': 'Qualified',
            'expected_value': '10',
        })

        self.assertEqual(list(form.fields['status'].choices), [('New', 'New')])
        self.assertFalse(form.is_valid())
        self.assertIn('status', form.errors)

    def test_lead_api_rejects_non_new_status_on_creation(self):
        payload = {
            'lead_name': 'API Lead',
            'email': 'api-lead@example.test',
            'phone': '6567890123',
            'source': 'Website',
            'status': 'Converted',
            'expected_value': '10.00',
        }

        self.client.force_login(self.sales_user)
        response = self.client.post(
            '/api/leads',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('status', response.json()['errors'])

    def test_manager_can_view_audit_but_not_user_entity_events(self):
        AuditLog.objects.create(
            user=self.manager,
            action='PrivateUserAction',
            entity_name='User',
            record_id='1',
        )
        AuditLog.objects.create(
            user=self.manager,
            action='CustomerAction',
            entity_name='Customer',
            record_id=str(self.customer.pk),
        )
        self.client.force_login(self.manager)

        response = self.client.get('/audit/', HTTP_HOST='localhost')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CustomerAction')
        self.assertNotContains(response, 'PrivateUserAction')

    def test_list_status_filters_are_selects_with_model_status_values(self):
        self.client.force_login(self.admin)

        customers = self.client.get('/customers/', HTTP_HOST='localhost')
        opportunities = self.client.get('/opportunities/', HTTP_HOST='localhost')

        self.assertContains(customers, 'name="status"')
        self.assertEqual(customers.context['status_choices'], [('Active', 'Active'), ('Inactive', 'Inactive')])
        self.assertEqual(
            opportunities.context['status_choices'],
            [('Open', 'Open'), ('Won', 'Won'), ('Lost', 'Lost')],
        )
        open_opportunities = self.client.get('/opportunities/?status=open', HTTP_HOST='localhost')
        self.assertEqual(
            [opportunity.status for opportunity in open_opportunities.context['object_list']],
            ['Open'],
        )

    def test_list_pagination_query_preserves_filters_without_page(self):
        self.client.force_login(self.admin)
        FollowUp.objects.bulk_create([
            FollowUp(
                customer=self.customer,
                follow_up_date=date(2026, 6, 1),
                follow_up_type='Call',
                remarks='call',
                status='Planned',
                assigned_to=self.admin,
            )
            for _ in range(11)
        ])

        response = self.client.get(
            '/followups/?q=call&status=planned&date=2026-06-01&page=2',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(
            response.context['qs_without_page'],
            'q=call&status=planned&date=2026-06-01',
        )
        self.assertContains(
            response,
            '?q=call&amp;status=planned&amp;date=2026-06-01&amp;page=1',
        )

    def test_list_pagination_omits_empty_filter_values(self):
        self.client.force_login(self.admin)

        response = self.client.get('/customers/?q=&status=&date=&page=1', HTTP_HOST='localhost')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['qs_without_page'], '')

    def test_audit_pagination_query_preserves_all_filters(self):
        AuditLog.objects.bulk_create([
            AuditLog(
                user=self.manager,
                action='Update',
                entity_name='Customer',
                record_id=str(index),
            )
            for index in range(21)
        ])
        self.client.force_login(self.manager)

        response = self.client.get(
            '/audit/?user=manager&entity=Customer&action=Update&from=2000-01-01&to=2099-12-31&page=1',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['qs_without_page'],
            'user=manager&entity=Customer&action=Update&from=2000-01-01&to=2099-12-31',
        )
        self.assertContains(
            response,
            '?user=manager&amp;entity=Customer&amp;action=Update&amp;from=2000-01-01&amp;to=2099-12-31&amp;page=2',
        )

    def test_report_pagination_uses_shared_filter_query(self):
        for index in range(14):
            Customer.objects.create(
                customer_name=f'Report Customer {index}',
                email=f'report-{index}@example.test',
                phone=f'70000000{index:02d}',
                created_by=self.admin,
            )
        self.client.force_login(self.admin)

        response = self.client.get(
            '/reports/customers/?status=Active&from=2000-01-01&to=2099-12-31&page=1',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['qs_without_page'],
            'status=Active&from=2000-01-01&to=2099-12-31',
        )
        self.assertContains(
            response,
            '?status=Active&amp;from=2000-01-01&amp;to=2099-12-31&amp;page=2',
        )

    def test_axes_lockout_template_is_configured_and_styled(self):
        self.assertEqual(settings.AXES_LOCKOUT_TEMPLATE, 'crm/lockout.html')
        request = RequestFactory().post('/accounts/login/', {'username': 'locked-user'})
        request.user = AnonymousUser()

        response = get_lockout_response(request)

        self.assertEqual(response.status_code, settings.AXES_HTTP_RESPONSE_CODE)
        self.assertContains(
            response,
            'Account locked, try again in 10 minutes.',
            status_code=settings.AXES_HTTP_RESPONSE_CODE,
        )

    def test_audit_ip_uses_remote_addr_not_forwarded_header(self):
        request = RequestFactory().get(
            '/',
            HTTP_X_FORWARDED_FOR='203.0.113.99',
            REMOTE_ADDR='192.0.2.10',
        )

        self.assertEqual(get_ip(request), '192.0.2.10')
