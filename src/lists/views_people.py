"""Saving cast, crew and authors on custom lists from a person page.

The Add-to-lists popup is shared with media. It reads the JSON that
``person_lists_modal`` returns (same shape as ``lists_modal``) and posts the
person's id to ``person_list_toggle``.
"""

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from app.models import Person
from lists.models import CustomList, CustomListPerson


def _clean_tags(custom_list):
    return [
        tag.strip()
        for tag in (custom_list.tags or [])
        if isinstance(tag, str) and tag.strip()
    ]


def list_people_for_display(custom_list):
    """Return the people saved on a list as name, picture and page link."""
    people = []
    for entry in custom_list.list_people.select_related("person"):
        person = entry.person
        people.append(
            {
                "id": person.id,
                "source": person.source,
                "person_id": person.source_person_id,
                "name": person.name,
                "image": person.image,
                "department": person.known_for_department,
                "url": reverse(
                    "person_detail",
                    args=[
                        person.source,
                        person.source_person_id,
                        slugify(person.name) or "person",
                    ],
                ),
            },
        )
    return people


def list_people_props(people):
    """Return the shared ListPeople island props for a list page, or None."""
    from django.conf import settings
    from django.utils.translation import gettext as _

    from app.templatetags.app_tags import image_url

    if not people:
        return None
    return {
        "kind": "listPeople",
        "title": str(_("People")),
        "people": [
            {
                "id": person["id"],
                "name": person["name"],
                "imageUrl": image_url(person["image"] or settings.IMG_NONE),
                "department": person["department"],
                "url": person["url"],
            }
            for person in people
        ],
    }


@login_required
@require_GET
def person_lists_modal(request, source, person_id):
    """Return the viewer's editable lists and whether each holds this person."""
    person = get_object_or_404(
        Person,
        source=source,
        source_person_id=str(person_id),
    )
    custom_lists = list(
        CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
            is_smart=False,
        )
        .annotate(
            has_item=Exists(
                CustomListPerson.objects.filter(
                    custom_list_id=OuterRef("id"),
                    person=person,
                ),
            ),
        )
        .distinct()
        .order_by("name"),
    )
    tags = sorted(
        {tag for custom_list in custom_lists for tag in _clean_tags(custom_list)},
        key=str.lower,
    )
    return JsonResponse(
        {
            "itemId": person.id,
            "title": person.name,
            "lists": [
                {
                    "id": custom_list.id,
                    "name": custom_list.name,
                    "hasItem": bool(custom_list.has_item),
                    "tags": _clean_tags(custom_list),
                }
                for custom_list in custom_lists
            ],
            "tags": tags,
            "selectedTag": "",
            "toggleUrl": reverse("person_list_toggle"),
            "createUrl": reverse("list_create"),
            "csrfToken": get_token(request),
        },
    )


@login_required
@require_POST
def person_list_toggle(request):
    """Add or remove a person from a custom list."""
    person = get_object_or_404(Person, id=request.POST["item_id"])
    custom_list = get_object_or_404(CustomList, id=request.POST["custom_list_id"])
    if not custom_list.user_can_view(request.user):
        msg = "List not found"
        raise Http404(msg)
    if not custom_list.user_can_edit(request.user) or custom_list.is_smart:
        return JsonResponse(
            {"success": False, "error": "This list cannot be edited."},
            status=403,
        )
    with transaction.atomic():
        removed, _ = CustomListPerson.objects.filter(
            custom_list=custom_list,
            person=person,
        ).delete()
        if not removed:
            CustomListPerson.objects.get_or_create(
                custom_list=custom_list,
                person=person,
                defaults={"added_by": request.user},
            )
    return JsonResponse({"success": True, "hasItem": not removed})
