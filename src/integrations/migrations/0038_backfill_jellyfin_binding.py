"""Map today's Jellyfin authorization onto sync bindings, broadening nothing.

Jellyfin is the only integration with real direction toggles, and they are
spread across two models. This translates them into bindings exactly as they
stand, so that after the migration a user can do precisely what they could do
before it.

The subtle one is ``push_watched_enabled``, which defaults to True but pushes
nothing unless ``scheduled_push_enabled`` or ``instant_push_enabled`` is also
set. Granting an outbound capability on that flag alone would hand a write
direction to every Jellyfin user who never turned pushing on, which is the
silent broadening this migration exists to avoid.

No bindings are created for Plex, Emby, Kodi, Stremio or Audiobookshelf: no
state direction was ever enabled for them, so an active binding would be a new
permission rather than a preserved one. They get theirs on first connect.
"""

import secrets

from django.db import migrations

# Repeated rather than imported: a migration must keep working when the
# constants in integrations.models are renamed or moved.
CAPABILITY_WATCHED_READ = "watched.read"
CAPABILITY_WATCHED_WRITE_PLAYED = "watched.write_played"
CAPABILITY_WATCHED_WRITE_UNPLAYED = "watched.write_unplayed"
CAPABILITY_WATCHED_PUSH_PLAYED = "watched.push_played"
CAPABILITY_WATCHED_PUSH_UNPLAYED = "watched.push_unplayed"

DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"


def _capabilities_for(user, account):
    """Return the capabilities and directions this user already had."""
    capabilities = []
    directions = []

    if getattr(user, "jellyfin_mark_played_enabled", False):
        capabilities.append(CAPABILITY_WATCHED_WRITE_PLAYED)
    if getattr(user, "jellyfin_mark_unplayed_enabled", False):
        capabilities.append(CAPABILITY_WATCHED_WRITE_UNPLAYED)
    if capabilities:
        directions.append(DIRECTION_INBOUND)

    if account is not None:
        # Pulling history is an inbound read, and it is on by default.
        if account.pull_history_enabled:
            capabilities.append(CAPABILITY_WATCHED_READ)
            if DIRECTION_INBOUND not in directions:
                directions.append(DIRECTION_INBOUND)

        pushing = account.scheduled_push_enabled or account.instant_push_enabled
        if pushing and account.push_watched_enabled:
            capabilities.append(CAPABILITY_WATCHED_PUSH_PLAYED)
        if pushing and account.push_unwatched_enabled:
            capabilities.append(CAPABILITY_WATCHED_PUSH_UNPLAYED)
        if pushing and (
            account.push_watched_enabled or account.push_unwatched_enabled
        ):
            directions.append(DIRECTION_OUTBOUND)

    return sorted(set(capabilities)), sorted(set(directions))


def create_jellyfin_bindings(apps, schema_editor):
    """Create one binding per Jellyfin-connected user, preserving permissions."""
    user_model = apps.get_model("users", "User")
    jellyfin_account_model = apps.get_model("integrations", "JellyfinAccount")
    sync_binding = apps.get_model("integrations", "SyncBinding")
    watch_state_sequence = apps.get_model("app", "WatchStateSequence")

    accounts = {
        account.user_id: account for account in jellyfin_account_model.objects.all()
    }

    # Users with the mark-played flags but no account are covered too: they
    # already accept inbound manual events through the webhook, and dropping
    # them would revoke something that works today.
    candidate_ids = set(accounts)
    candidate_ids.update(
        user_model.objects.filter(jellyfin_mark_played_enabled=True).values_list(
            "id",
            flat=True,
        ),
    )
    candidate_ids.update(
        user_model.objects.filter(jellyfin_mark_unplayed_enabled=True).values_list(
            "id",
            flat=True,
        ),
    )
    if not candidate_ids:
        return

    for user in user_model.objects.filter(id__in=candidate_ids):
        account = accounts.get(user.id)
        capabilities, directions = _capabilities_for(user, account)

        sync_binding.objects.create(
            user_id=user.id,
            client_kind="jellyfin",
            # Jellyfin's server id is not stored yet, so the binding starts
            # unscoped and the first payload carrying one narrows it. That is
            # a narrowing of an approval already given, not a new one.
            instance_key="",
            profile_key=(account.jellyfin_user_id if account else ""),
            origin_key=f"jellyfin_{secrets.token_urlsafe(16)}",
            approved_capabilities=capabilities,
            approved_directions=directions,
            # A binding with nothing approved must not be active: it would
            # claim a permission the user never had.
            status="active" if capabilities else "pending",
            kill_switch=False,
            label=(account.base_url if account else ""),
        )

        if capabilities:
            sequence, _created = watch_state_sequence.objects.get_or_create(
                user_id=user.id,
                defaults={"last_sequence": 0, "emit_changes": True},
            )
            if not sequence.emit_changes:
                sequence.emit_changes = True
                sequence.save(update_fields=["emit_changes"])


def remove_jellyfin_bindings(apps, schema_editor):
    """Drop the bindings this migration created."""
    sync_binding = apps.get_model("integrations", "SyncBinding")
    sync_binding.objects.filter(client_kind="jellyfin").delete()

    watch_state_sequence = apps.get_model("app", "WatchStateSequence")
    watch_state_sequence.objects.filter(emit_changes=True).update(emit_changes=False)


class Migration(migrations.Migration):
    """Translate Jellyfin's existing toggles into bindings."""

    dependencies = [
        ("integrations", "0037_syncbinding_and_more"),
        ("app", "0178_watchstate_watchstatechange_watchstatesequence"),
    ]

    operations = [
        migrations.RunPython(create_jellyfin_bindings, remove_jellyfin_bindings),
    ]
