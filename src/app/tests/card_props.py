"""Read a rendered media card the way React does: from its props, not its markup.

The server sends each card as a props script plus a first-paint shell, and
`frontend/ui/MediaCard.jsx` draws the rest. Tests that care about a chip, a
rating or a hover button therefore assert on the model.
"""

import json
import re

PROPS = re.compile(
    r'<script id="(media-card-[^"]*|history-card-[^"]*|media-row-[^"]*)" '
    r'type="application/json">(.*?)</script>',
    re.DOTALL,
)


def card_models(content):
    """Return every card model in ``content``, in page order."""
    if isinstance(content, bytes):
        content = content.decode()
    return [json.loads(body)["model"] for _id, body in PROPS.findall(content)]


def card_model(card_html):
    """Return the one model in a fragment of HTML."""
    models = card_models(str(card_html))
    if len(models) != 1:
        msg = f"expected one card, found {len(models)}"
        raise AssertionError(msg)
    return models[0]


def card_text(content):
    """Return ``content`` with each props script written as readable text."""
    if isinstance(content, bytes):
        content = content.decode()
    return PROPS.sub(
        lambda m: json.dumps(json.loads(m.group(2)), ensure_ascii=False),
        content,
    )


def corner_chip(model, kind):
    """Return the corner chip of ``kind``, or None."""
    return next((c for c in model["cornerChips"] if c["kind"] == kind), None)


def render_card_template(context, request=None):
    """Render the card template for a hand-built context, as the tag would.

    Production only reaches the template through ``{% media_card %}``; a few
    tests drive it with an ad-hoc context to pin one behaviour.
    """
    from django.template.loader import render_to_string

    from app.card_surfaces import _attach_react_card, _card_render_context

    ctx = {"react_card": True, "card_uid": "test", **context}
    if request is not None:
        ctx.setdefault("request", request)
        ctx.setdefault("user", request.user)
    ctx.update(_card_render_context(ctx))
    _attach_react_card(ctx)
    return render_to_string("app/components/media_card.html", ctx, request=request)
