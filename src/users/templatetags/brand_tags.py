from django import template

from users.branding import brand_for_viewer

register = template.Library()


@register.simple_tag
def branding_for(user):
    """Resolve personal branding or the deliberately published public copy."""
    return brand_for_viewer(user)
