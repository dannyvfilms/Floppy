from allauth.account.adapter import DefaultAccountAdapter


class NoNewUsersAccountAdapter(DefaultAccountAdapter):
    """Custom account adapter to prevent new users from signing up."""

    def is_open_for_signup(self, request):
        """Check whether or not the site is open for signups."""
        return False
