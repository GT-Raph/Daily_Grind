from django.contrib.auth.forms import AuthenticationForm


def can_view_orders(user):
    return user.is_active and user.is_staff and user.has_perm("website.view_order")


class StaffAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Unable to sign in. Check your staff username and password, or ask your manager for access.",
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not can_view_orders(user):
            raise self.get_invalid_login_error()
