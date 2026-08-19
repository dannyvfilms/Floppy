import apprise
from allauth.account.adapter import get_adapter
from allauth.account.forms import LoginForm, SignupForm
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from .models import User

USERNAME_TAKEN_ERROR_CODE = "username_taken"


class CustomLoginForm(LoginForm):
    """Custom login form for django-allauth."""

    def __init__(self, *args, **kwargs):
        """Remove email field and change password2 label."""
        super().__init__(*args, **kwargs)

        self.fields["login"].widget.attrs["placeholder"] = "Enter your username"

        self.fields["password"].widget.attrs["placeholder"] = "Enter your password"


class CustomSignupForm(SignupForm):
    """Custom signup form for django-allauth."""

    def __init__(self, *args, **kwargs):
        """Remove email field and change password2 label."""
        super().__init__(*args, **kwargs)

        # Use pop instead of del: allauth already omits this field when
        # ACCOUNT_SIGNUP_FIELDS excludes email, so a plain `del` would raise
        # an unhandled KeyError (-> 500) in that configuration.
        self.fields.pop("email", None)

        # Change label and placeholder for password2 field
        self.fields["password2"].label = "Confirm Password"
        self.fields["password2"].widget.attrs["placeholder"] = "Confirm your password"

    def save(self, request):
        """Save the new user, turning a race-condition IntegrityError into a form error."""
        try:
            return super().save(request)
        except IntegrityError as exc:
            raise get_adapter().validation_error(USERNAME_TAKEN_ERROR_CODE) from exc


class CustomSocialSignupForm(SocialSignupForm):
    """Custom OIDC/social account signup form for django-allauth."""

    def __init__(self, *args, **kwargs):
        """Remove email field, mirroring local signup."""
        super().__init__(*args, **kwargs)

        self.fields.pop("email", None)

    def save(self, request):
        """Save the new user, turning a race-condition IntegrityError into a form error."""
        try:
            return super().save(request)
        except IntegrityError as exc:
            raise get_adapter().validation_error(USERNAME_TAKEN_ERROR_CODE) from exc


class UserUpdateForm(forms.ModelForm):
    """Custom form for updating username."""

    def clean(self):
        """Check if the user is demo before changing the password."""
        cleaned_data = super().clean()
        if self.instance.is_demo:
            msg = "Changing the username is not allowed for the demo account."
            self.add_error("username", msg)
        return cleaned_data

    def __init__(self, *args, **kwargs):
        """Add crispy form helper to add submit button."""
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = None

    class Meta:
        """Only allow updating username."""

        model = User
        fields = ["username"]


class PasswordChangeForm(PasswordChangeForm):
    """Custom form for changing password."""

    def clean(self):
        """Check if the user is demo before changing the password."""
        cleaned_data = super().clean()
        if self.user.is_demo:
            msg = "Changing the password is not allowed for the demo account."
            self.add_error("new_password2", msg)
        return cleaned_data

    def __init__(self, *args, **kwargs):
        """Remove autofocus from password change form."""
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.pop("autofocus", None)
        self.fields["new_password1"].help_text = None


class NotificationSettingsForm(forms.ModelForm):
    """Form for notification settings."""

    class Meta:
        """Form fields for notification settings."""

        model = User
        fields = [
            "notification_urls",
            "daily_digest_enabled",
            "release_notifications_enabled",
            "premiere_notifications_enabled",
        ]
        widgets = {
            "notification_urls": forms.Textarea(
                attrs={
                    "rows": 5,
                    "wrap": "off",
                    "placeholder": (
                        "discord://webhook_id/webhook_token\n"
                        "tgram://bot_token/chat_id\n"
                        "notifiarr://api_key/#channel_id"
                    ),
                },
            ),
        }

    def clean_notification_urls(self):
        """Validate that each URL is a valid Apprise URL."""
        notification_urls = self.cleaned_data.get("notification_urls", "")

        if not notification_urls.strip():
            return notification_urls

        # Create Apprise instance for validation
        apobj = apprise.Apprise()

        # Check each URL
        urls = [url.strip() for url in notification_urls.splitlines() if url.strip()]

        for url in urls:
            if not apobj.add(url):
                message = f"'{url}' is not a valid Apprise URL."
                raise ValidationError(message)

        return notification_urls


class AuthenticatorSetupForm(forms.Form):
    """Confirm authenticator app setup with a TOTP code."""

    code = forms.CharField(max_length=6, min_length=6)

    def __init__(self, *args, user, **kwargs):
        """Store the extra keyword arguments this form needs."""
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_code(self):
        """Validate TOTP code against the user's pending secret."""
        code = self.cleaned_data["code"].strip()
        if not self.user.verify_totp_code(code):
            msg = "Invalid authenticator code."
            raise ValidationError(msg)
        return code


class RegenerateRecoveryCodesForm(forms.Form):
    """Regenerate recovery codes with password confirmation."""

    current_password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, user, **kwargs):
        """Store the extra keyword arguments this form needs."""
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        """Validate the current password field."""
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            msg = "Current password is incorrect."
            raise ValidationError(msg)
        return password


class PasswordRecoveryForm(SetPasswordForm):
    """Self-service password recovery using recovery codes and authenticator."""

    username = forms.CharField(max_length=150)
    recovery_code = forms.CharField(max_length=32, required=False)
    authenticator_code = forms.CharField(required=False, max_length=6)

    error_messages = {
        "invalid_recovery": "Unable to verify recovery details.",
    }

    def __init__(self, *args, **kwargs):
        """Store the extra keyword arguments this form needs."""
        super().__init__(None, *args, **kwargs)
        self.recovery_instance = None

    def clean(self):
        """Validate the submitted data as a whole."""
        cleaned_data = super().clean()
        username = cleaned_data.get("username", "").strip()
        recovery_code = cleaned_data.get("recovery_code", "").strip().upper()
        authenticator_code = cleaned_data.get("authenticator_code", "").strip()

        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            raise ValidationError(self.error_messages["invalid_recovery"])

        has_valid_authenticator_code = (
            user.has_authenticator_configured
            and bool(
                authenticator_code,
            )
            and user.verify_totp_code(authenticator_code)
        )

        matching_recovery = None
        if recovery_code:
            for code in user.recovery_codes.filter(used_at__isnull=True):
                if code.matches(recovery_code):
                    matching_recovery = code
                    break

        if user.has_authenticator_configured:
            if not has_valid_authenticator_code and matching_recovery is None:
                raise ValidationError(self.error_messages["invalid_recovery"])
            if has_valid_authenticator_code:
                # Don't burn a recovery code when authenticator verification already succeeded.
                matching_recovery = None
        elif matching_recovery is None:
            raise ValidationError(self.error_messages["invalid_recovery"])

        self.user = user
        self.recovery_instance = matching_recovery
        return cleaned_data

    def save(self, commit=True):
        """Return the save."""
        user = super().save(commit=commit)
        if self.recovery_instance:
            self.recovery_instance.used_at = timezone.now()
            self.recovery_instance.save(update_fields=["used_at"])
        return user
