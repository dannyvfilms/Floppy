#!/usr/bin/env python3
"""Refresh Django catalogs, including JavaScript embedded in HTML templates."""

import argparse
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

DYNAMIC = "__FLOPPY_TEMPLATE_EXPRESSION__"
STRING = r"'(?:\\[\s\S]|[^'\\])*'|\"(?:\\[\s\S]|[^\"\\])*\""
LITERAL = re.compile(STRING)
TOKEN = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|" + STRING + r"|`(?:\\[\s\S]|[^`\\])*`|"
    r"(?<![\w$.])(?:window\.|django\.)?"
    r"(?P<function>gettext|ngettext|pgettext|npgettext)\s*\(",
)
TRIVIA = re.compile(r"(?:\s|//[^\n]*(?:\n|$)|/\*[\s\S]*?\*/)*")
ARGUMENTS = {"gettext": 1, "ngettext": 2, "pgettext": 2, "npgettext": 3}


def literal_calls(javascript):
    """Yield extraction-only calls whose message arguments are static literals."""
    for token in TOKEN.finditer(javascript):
        function = token.group("function")
        if function is None:
            continue
        position = token.end()
        literals = []
        for index in range(ARGUMENTS[function]):
            position = TRIVIA.match(javascript, position).end()
            literal = LITERAL.match(javascript, position)
            if literal is None or DYNAMIC in literal.group():
                break
            literals.append(literal.group())
            position = TRIVIA.match(javascript, literal.end()).end()
            separator = "," if index + 1 < ARGUMENTS[function] else None
            if separator:
                if javascript[position : position + 1] != separator:
                    break
                position += 1
        else:
            plural = function in {"ngettext", "npgettext"}
            expected = "," if plural else ")"
            if javascript[position : position + 1] == expected:
                # The count is irrelevant to extraction; never evaluate source code.
                if plural:
                    literals.append("2")
                yield f"{function}({', '.join(literals)});"


class InlineJavaScript(HTMLParser):
    """Collect script bodies and browser/Alpine/HTMX event attributes."""

    def __init__(self):
        """Initialize the parser without rendering Django template expressions."""
        super().__init__(convert_charrefs=True)
        self.snippets = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        """Collect executable attributes and detect the start of a script."""
        if tag == "script":
            self.in_script = True
        for name, value in attrs:
            if value and name.startswith(("x-", "@", ":", "on", "hx-on")):
                self.snippets.append(value)

    def handle_endtag(self, tag):
        """Stop collecting script text at its closing tag."""
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        """Collect JavaScript bodies while ignoring ordinary visible text."""
        if self.in_script:
            self.snippets.append(data)


def extract_inline_calls(template):
    """Extract literal gettext calls without rendering or importing the template."""
    # Verbatim examples can contain Handlebars {{#...}}, which is not a Django
    # {# comment. Remove them before processing Django comments or expressions.
    template = re.sub(
        r"{%\s*verbatim(?:\s+\w+)?\s*%}[\s\S]*?"
        r"{%\s*endverbatim(?:\s+\w+)?\s*%}",
        DYNAMIC,
        template,
    )
    template = re.sub(
        r"{%\s*comment\b[\s\S]*?{%\s*endcomment\s*%}|{#[\s\S]*?#}",
        "",
        template,
    )
    # Prevent Django's quoted expressions from confusing HTML attribute parsing.
    # Their placeholder also makes dynamic gettext arguments ineligible.
    template = re.sub(r"{{[\s\S]*?}}|{%[\s\S]*?%}", DYNAMIC, template)
    parser = InlineJavaScript()
    parser.feed(template)
    return list(
        dict.fromkeys(
            call for snippet in parser.snippets for call in literal_calls(snippet)
        ),
    )


def write_inline_sources(source_root, destination):
    """Write generated JS with paths traceable to the original HTML templates."""
    for template in sorted((source_root / "templates").rglob("*.html")):
        calls = extract_inline_calls(template.read_text(encoding="utf-8"))
        if calls:
            relative = template.relative_to(source_root)
            target = destination / relative.with_suffix(".html.js")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"// Generated from {relative.as_posix()}; do not edit.\n"
                + "\n".join(calls)
                + "\n",
                encoding="utf-8",
            )


def update_catalogs(source_root, locales):
    """Run both native Django extraction domains and always remove generated JS."""
    generated = source_root / "inline_translation_extraction"
    # Refuse to overwrite any pre-existing directory, including an interrupted run.
    generated.mkdir()
    try:
        write_inline_sources(source_root, generated)
        locale_args = [argument for locale in locales for argument in ("-l", locale)]
        for domain in ("django", "djangojs"):
            # Bundled libraries own their UI/locales; gettext-like identifiers
            # inside minified third-party code are not Floppy messages.
            ignores = ["--ignore=static/js/libraries/*"] if domain == "djangojs" else []
            subprocess.run(  # noqa: S603 -- fixed local command, argument list, no shell
                [
                    sys.executable,
                    str(source_root / "manage.py"),
                    "makemessages",
                    "-d",
                    domain,
                    *locale_args,
                    *ignores,
                ],
                cwd=source_root,
                check=True,
            )
    finally:
        shutil.rmtree(generated)


def main():
    """Parse target locales and refresh catalogs in this checkout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-l", "--locale", action="append", required=True)
    args = parser.parse_args()
    update_catalogs(Path(__file__).resolve().parents[1] / "src", args.locale)


if __name__ == "__main__":
    main()
