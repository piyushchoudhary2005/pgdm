from django.test import TestCase

import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import override_settings

from .forms import LeadForm
from .models import AuditLog, Customer, Lead, Opportunity


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
