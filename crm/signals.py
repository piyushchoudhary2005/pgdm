from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from axes.signals import user_locked_out
from django.dispatch import receiver
from .audit import log_audit

@receiver(user_logged_in)
def on_login(sender, request, user, **kw): log_audit(request, 'Login', 'User', user.pk, user=user)

@receiver(user_logged_out)
def on_logout(sender, request, user, **kw):
    if user: log_audit(request, 'Logout', 'User', user.pk, user=user)

@receiver(user_login_failed)
def on_fail(sender, credentials=None, request=None, **kw):
    log_audit(request, 'FailedLogin', 'User', '', None, (credentials or {}).get('username'))   # never log the password

@receiver(user_locked_out)
def on_lock(sender, request=None, username=None, **kw):
    log_audit(request, 'Lockout', 'User', '', None, username)