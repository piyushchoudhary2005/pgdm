from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    def handle(self, *a, **k):
        for r in ['Admin', 'Manager', 'SalesExecutive']: Group.objects.get_or_create(name=r)
        for name, r in [('admin1', 'Admin'), ('manager1', 'Manager'), ('sales1', 'SalesExecutive'), ('sales2', 'SalesExecutive')]:
            u, created = User.objects.get_or_create(username=name, defaults={'email': f'{name}@acxiom.test'})
            if created:
                u.set_password('Test@1234'); u.save()
            u.groups.set([Group.objects.get(name=r)])