from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied

ROLES = ['Admin', 'Manager', 'SalesExecutive']

def role(user):
    if not user.is_authenticated: return None
    if user.is_superuser: return 'Admin'
    names = set(user.groups.values_list('name', flat=True))
    for r in ROLES:
        if r in names: return r
    return 'SalesExecutive'            # least privilege by default

from django.db.models import Q
CUSTOMER_SCOPE = 'created_by|assigned_to'

def scope(user, qs, field):
    if role(user) in ('Admin', 'Manager'): return qs
    cond = Q()
    for f in field.split('|'): cond |= Q(**{f: user})
    return qs.filter(cond)
def require_role(request, *roles):
    if role(request.user) not in roles: raise PermissionDenied

class RoleRequiredMixin(UserPassesTestMixin):
    allowed_roles = ()
    def test_func(self): return role(self.request.user) in self.allowed_roles