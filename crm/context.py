from django.utils import timezone
from .access import role, scope
from .models import FollowUp

def role_ctx(request):
    n = 0
    if request.user.is_authenticated:
        n = scope(request.user, FollowUp.objects.all(), 'assigned_to').filter(
            status='Planned', follow_up_date__lte=timezone.localdate()).count()
    return {'role': role(request.user), 'due_count': n}