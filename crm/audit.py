import json
from django.forms.models import model_to_dict
from .models import AuditLog

def get_ip(request):
    if request is None: return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

def dump(obj): return json.dumps(model_to_dict(obj), default=str)

def log_audit(request, action, entity, record_id='', old=None, new=None, user=None):
    u = user or (getattr(request, 'user', None) if request else None)
    if u is not None and not u.is_authenticated: u = None
    AuditLog.objects.create(user=u, action=action, entity_name=entity, record_id=str(record_id),
                            old_value=old, new_value=new, ip_address=get_ip(request))