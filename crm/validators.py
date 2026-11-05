import re
from django.core.exceptions import ValidationError

class ComplexityValidator:
    def validate(self, password, user=None):
        if not (re.search(r'[A-Z]', password) and re.search(r'[a-z]', password)
                and re.search(r'\d', password) and re.search(r'\W', password)):
            raise ValidationError('Password needs upper, lower, digit and special character.')
    def get_help_text(self):
        return 'Use upper, lower, digit and special character.'