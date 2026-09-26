"""Turn recorded state changes into outbound delivery intents.

This is the seam between the two layers. ``app`` owns canonical state and must
not know that integrations exist; ``integrations`` listens to app's change log
and decides who should hear about it. The listener runs inside the change's own
transaction, which is what makes the outbox atomic — the change and the intent
to deliver it commit together or not at all.
"""

import logging

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_save
from django.dispatch import receiver

from app.models import TV, Season, WatchState, WatchStateChange
from integrations.state.outbound import enqueue_deliveries, schedule_delivery

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Season)
@receiver(post_save, sender=TV)
@receiver(post_save, sender=WatchState)
def sync_grouped_anime_change(sender, instance, **kwargs):
    """Push grouped anime changes after the tracking transaction commits."""
    from app.signals import media_change_side_effects_suppressed
    from integrations.mal_sync import queue_grouped_sync

    if kwargs.get("raw") or media_change_side_effects_suppressed():
        return
    if sender is WatchState and instance.item.media_type != "episode":
        return
    try:
        queue_grouped_sync(instance.user_id, instance.item)
    except ObjectDoesNotExist:
        return


@receiver(post_save, sender=WatchStateChange)
def enqueue_on_state_change(sender, instance, created, **kwargs):
    """Record delivery intents for a newly recorded change."""
    if not created:
        return

    for delivery in enqueue_deliveries(instance):
        schedule_delivery(delivery)
