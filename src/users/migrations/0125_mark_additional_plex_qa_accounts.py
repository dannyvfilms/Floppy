from django.db import migrations


KNOWN_TEST_USERNAMES = frozenset(
    {
        "codex_debug_localonly",
        "facetcheck",
    }
)


def mark_additional_test_accounts(apps, schema_editor):
    """Tag QA accounts that were identified after the initial backfill."""
    user_model = apps.get_model("users", "User")
    test_user_ids = [
        user.pk
        for user in user_model.objects.filter(is_test_account=False)
        .only("pk", "username")
        .iterator()
        if user.username.casefold() in KNOWN_TEST_USERNAMES
    ]
    if test_user_ids:
        user_model.objects.filter(pk__in=test_user_ids).update(is_test_account=True)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0124_alter_user_managers_user_is_test_account"),
    ]

    operations = [
        migrations.RunPython(mark_additional_test_accounts, migrations.RunPython.noop),
    ]
