from django import template

from users.server_port_views import server_port_context

register = template.Library()


@register.inclusion_tag("users/components/server_port.html", takes_context=True)
def server_port_panel(context):
    """Render server-port status, with mutation controls only for a superuser."""
    request = context.get("request")
    if request is None or not request.user.is_authenticated:
        return {
            "show_server_port_panel": False,
            "can_manage_server_port": False,
        }

    return {
        "show_server_port_panel": True,
        "can_manage_server_port": request.user.is_superuser,
        **server_port_context(),
    }
