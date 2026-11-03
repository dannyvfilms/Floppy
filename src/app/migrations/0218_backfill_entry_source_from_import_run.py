from django.db import migrations
from django.db.models import CharField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce


def fill_blank_entry_sources(apps, schema_editor):
    """Record the importer on entries it created that have no source yet.

    Only blank values are filled, and only where the entry names the import
    run that wrote it, so nothing a person typed is touched. Historical rows
    keep the run id after the run is deleted, so a missing run resolves to
    blank rather than NULL, and those rows are left alone.
    """
    ImportRun = apps.get_model("integrations", "ImportRun")
    run_source = ImportRun.objects.filter(pk=OuterRef("import_run_id")).values(
        "source",
    )[:1]
    for model in apps.get_app_config("app").get_models():
        field_names = {field.name for field in model._meta.get_fields()}
        if not {"import_run", "entry_source"} <= field_names:
            continue
        model.objects.filter(entry_source="", import_run_id__isnull=False).update(
            entry_source=Coalesce(
                Subquery(run_source),
                Value(""),
                output_field=CharField(),
            ),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0217_podcastindex_source"),
        ("integrations", "0063_wetrakr_account"),
    ]

    operations = [
        migrations.RunPython(fill_blank_entry_sources, migrations.RunPython.noop),
    ]
