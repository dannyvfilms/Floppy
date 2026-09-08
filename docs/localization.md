# Localization workflow

Use English source messages and Django gettext markers. Keep persisted values,
API identifiers, filter values, and statistics keys unchanged. Translate their
display labels at the presentation boundary.

## Refresh and compile

With the project environment and GNU gettext tools installed:

```sh
uv run --no-sync python scripts/update_translations.py -l de
```

This runs native `makemessages` for both `django` (Python/templates) and
`djangojs` (JavaScript), preserving existing translations through Django's normal
merge. Review changed PO files and translate new or fuzzy entries, then compile:

```sh
cd src
uv run --project .. --no-sync python manage.py compilemessages -l de
```

Repeat `-l` to refresh several languages. The commands use the normal Django
environment, including its `SECRET` setting. Rebuild/restart the application to
load compiled catalogs.

## Inline JavaScript

Native JavaScript extraction does not scan HTML templates. The update script
collects literal `gettext`, `ngettext`, `pgettext`, and `npgettext` calls from
`<script>` bodies and Alpine/browser/HTMX event attributes. It writes temporary
JavaScript under `src/inline_translation_extraction/`, runs both Django domains,
and removes that directory in `finally`. Generated PO references mirror original
template paths with `.js` appended. There is no maintained duplicate string list.
Bundled third-party files under `static/js/libraries/` are excluded from this
application catalog. Verbatim template examples are ignored before extraction.

Use complete literal messages, for example `gettext('Save')` or
`ngettext('One item', 'Many items', count)`. Calls through `window` or `django`
are supported. Dynamic arguments, concatenations, comments, and backtick strings
are deliberately ignored; keep gettext calls outside template-literal
interpolations. This is an extraction helper, not a general JavaScript parser.
It never executes the JavaScript or changes template values.

For labels selected dynamically, mark every English possibility at its source.
`gettext_noop` in Python makes a label extractable without translating the value
used by application logic; `{% translate label %}` translates its display later.
Python no-op labels belong to the `django` domain. A dynamic JavaScript
`gettext(label)` instead requires JavaScript-domain literal markers; prefer
translating a Python label in the template with `translate … as` plus `escapejs`
before passing it to JavaScript. Never rely on manually added, unmarked PO entries:
normal catalog refreshes can obsolete them.

Template strings containing quotes are easiest to extract with `blocktranslate`.
For JavaScript placeholders derived in templates, use `blocktranslate … asvar`
and `escapejs`; avoid mixing Python-style `%` placeholders directly into a
template `translate` tag.

## Validate

```sh
uv run --no-sync python -m unittest discover -s scripts/tests -p test_update_translations.py
```

The tests cover escaped quotes, HTML entities, plurals, contextual messages,
ignored dynamic arguments, and cleanup after failure. When `xgettext` is
available they also extract a real temporary PO file. Application catalogs are
not modified by these tests. After refreshing, check both domains for unexpected
obsolete/fuzzy entries and smoke-test the affected screens in German and English.
