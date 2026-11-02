"""Server-owned content slots for the incremental React settings-card pilot."""

from uuid import uuid4

from django import template
from django.template.base import token_kwargs
from django.template.loader import render_to_string

register = template.Library()


@register.tag
def settings_card(parser, token):
    """Render a shared card without passing its forms or credentials to React."""
    bits = token.split_contents()
    options = token_kwargs(bits[1:], parser)
    allowed = {"title", "tone", "badge", "info_label", "info_title", "enabled"}
    if "title" not in options or set(options) - allowed or any("=" not in bit for bit in bits[1:]):
        message = "settings_card requires title and named presentation options only"
        raise template.TemplateSyntaxError(message)
    body = parser.parse(("endsettings_card",))
    parser.delete_first_token()
    return SettingsCardNode(options, body)


class SettingsCardNode(template.Node):
    """Compose escaped presentation props and a separately rendered content slot."""

    def __init__(self, options, body):
        """Keep the compiled expressions and Django body for each render."""
        self.options = options
        self.body = body

    def render(self, context):
        """Render the shell, or only its body for legacy dialog consumers."""
        if "enabled" in self.options and not self.options["enabled"].resolve(context):
            return self.body.render(context)
        props = {name: str(value.resolve(context)) for name, value in self.options.items()}
        props.pop("enabled", None)
        if props.get("tone") not in {"neutral", "info", "warning", "success"}:
            props["tone"] = "neutral"
        # The body remains Django HTML, outside the React root. Never serialize it.
        return render_to_string("users/components/settings_card.html", {
            "card": props,
            "props_id": f"settings-card-{uuid4().hex}",
            "body": self.body.render(context),
        })


@register.simple_tag
def settings_link_chip(label, url):
    """Render a shared link chip with a usable server fallback."""
    return render_to_string("users/components/settings_link_chip.html", {
        "chip": {"label": label, "href": url, "tone": "info",
                 "hrefAttrs": {"target": "_blank", "rel": "noopener"}},
        "props_id": f"settings-chip-{uuid4().hex}",
    })
