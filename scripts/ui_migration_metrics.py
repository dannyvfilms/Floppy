#!/usr/bin/env python3
# ruff: noqa: T201
"""Measure how much of Floppy's UI has moved to the shared React pattern.

Run from anywhere: ``python3 scripts/ui_migration_metrics.py`` (add ``--json`` for
machine-readable output, ``--templates`` to list every island-hosting template, ``--areas`` for the by-area table, ``--reach`` for the pattern counts behind the next-items list, ``--entries`` to list the
islands each register entry's own templates mount, ``--native`` for the per-file native-reuse classification).
Standard library only; reads tracked-or-not files under the repository root.

Three independent measures, defined in docs/ui/migration-measurement.md:

1. Register: how many component-register entries carry each status.
2. Templates: how many of ``src/templates/**/*.html`` host a React island, and what
   share of template lines they hold. "Hosts" is a presence count, not a claim that the
   whole template is migrated.
3. Code size: React lines (``frontend/``) against hand-written template lines and
   first-party JavaScript lines.

A fourth, separate measure answers a different question: how much of that React is
written so it could also run on iOS and Android (``--native`` lists it per file). It
is *not* a share of the web migration; see docs/architecture/ui-modernization.md.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "src/templates"
LOADER = ROOT / "frontend/settings/index.js"

# Template tags that render an island host (checked in the Python tag libraries).
ISLAND_TAGS = (
    "settings_card",      # users/templatetags/ui_tags.py
    "settings_link_chip",
    "rating_stars",
    "spinner",
    "badge",
    "button",
    "alphabet_filter",    # app/templatetags/alphabet_tags.py
    "media_card",         # app/templatetags/app_tags.py
    "history_card_react",
    "media_row_react",
    "global_search_react",
    "sidebar_react",
)

# The settings/provider pages put their islands behind ``provider_ui`` models and
# ``{% include %}`` of the *_island templates, so includes are followed transitively.
INCLUDE_RE = re.compile(r"""\{%-?\s*include\s+["']([^"']+)["']""")

# Small single-control islands. They are real islands, but a template that only hosts
# one of these (a Save button, a spinner) is still almost entirely legacy markup, so the
# report also gives the count without them ("substantive" islands).
ATOM_TAGS = ("spinner", "badge", "button", "settings_link_chip")
ATOM_MARKERS = ("data-spinner-root", "data-badge-root", "data-button-root", "data-link-chip-root")


def tag_re(tags) -> re.Pattern:
    """Match the supplied template tags."""
    return re.compile(r"\{%-?\s*(" + "|".join(tags) + r")\b")


def loader_markers() -> list[str]:
    """Read the mounted ``data-*-root`` attributes from the loader."""
    text = LOADER.read_text()
    selector = re.search(r"const selector = '([^']+)'", text)
    return re.findall(r"\[(data-[a-z-]+-root)\]", selector.group(1)) if selector else []


def template_files() -> list[Path]:
    """List HTML templates."""
    return sorted(TEMPLATES.rglob("*.html"))


def line_count(path: Path) -> int:
    """Count newline-terminated lines."""
    return path.read_bytes().count(b"\n")  # same as ``wc -l``


def hosting(markers: list[str], tags=ISLAND_TAGS) -> dict[str, dict]:
    """Return ``{relative template path: {"lines", "direct", "via_include"}}``."""
    marker_re = re.compile("|".join(re.escape(m) for m in markers))
    info: dict[str, dict] = {}
    for path in template_files():
        text = path.read_text(errors="ignore")
        rel = str(path.relative_to(TEMPLATES))
        info[rel] = {
            "lines": text.count("\n"),
            "direct": bool(marker_re.search(text)) or bool(tag_re(tags).search(text)),
            "includes": INCLUDE_RE.findall(text),
        }
    hosts = {rel for rel, d in info.items() if d["direct"]}
    changed = True
    while changed:  # follow includes of hosting templates; ``extends`` is not followed
        changed = False
        for rel, d in info.items():
            if rel not in hosts and any(inc in hosts for inc in d["includes"]):
                hosts.add(rel)
                d["via_include"] = True
                changed = True
    for rel, d in info.items():
        d["hosts"] = rel in hosts
        d.setdefault("via_include", False)
    return info


def lines_in(paths) -> int:
    """Count lines across files."""
    return sum(line_count(p) for p in paths)


def code_size() -> dict[str, int]:
    """Measure the relevant frontend source files."""
    frontend = [p for p in (ROOT / "frontend").rglob("*") if p.is_file()]
    react_js = [p for p in frontend if p.suffix in {".jsx", ".js"}]
    react_css = [p for p in frontend if p.suffix == ".css"]
    first_party_js = [
        p
        for p in (ROOT / "src/static/js").glob("*.js")  # top level only: not libraries/ or i18n/
        if p.is_file()
    ]
    templates = template_files()
    return {
        "react_js_lines": lines_in(react_js),
        "react_css_lines": lines_in(react_css),
        "react_total_lines": lines_in(react_js) + lines_in(react_css),
        "template_lines": lines_in(templates),
        "first_party_js_lines": lines_in(first_party_js),
        "first_party_js_files": len(first_party_js),
    }


# Credit per status for the register measure. TOKENS-style entries ("Existing (no UI
# work needed)") are left out of the denominator.
CREDIT = {"Web Migrated": 1.0, "Partial / coexisting": 0.5, "Legacy": 0.0, "Deferred (blocker)": 0.0}

# Which register entries make up each row of the by-area table.
AREAS = {
    "Shell and header search": ["SHELL", "SEARCH"],
    "Shared building blocks": [
        "SETTINGS-CARD", "FORM-CONTROLS", "SPINNER", "BADGE", "BUTTON", "RATING",
        "ARTWORK-LOADING", "ASYNC-STATE", "WEB-UTILITIES", "TOKENS",
    ],
    "Media card": ["MEDIA-CARD"],
    "Popups and tracking forms": ["POPUP-HOST", "TRACKING"],
    "Library, collection, search results": [
        "LIBRARY", "ALPHABET", "FILTERS", "TABLES", "BULK", "RAILS", "OWNERSHIP",
        "CUSTOM-FIELDS", "TAGS",
    ],
    "Home and Discover": ["HOME", "PLAYBACK", "DISCOVER"],
    "Media details": [
        "DETAIL", "CHILDREN", "DATE-TIME", "NOTES", "PROGRESS", "ARTWORK", "MUSIC",
        "PEOPLE", "METADATA-REVIEW", "DETAIL-RELATED",
    ],
    "History, Statistics, Calendar": ["HISTORY", "STATISTICS", "RELEASE-CALENDAR"],
    "Lists, smart lists, tiers": ["LISTS", "SMART-RULES", "LIST-CURATION", "TIERS"],
    "Provider pages and integrations": [
        "SET-PROVIDERS", "SET-METADATA", "SET-IMPORT", "SET-ACTIVITY", "SET-SYNC",
        "INTEGRATION-PANELS", "MATCH-REVIEW", "DEVICE-CONNECT", "STREMIO",
    ],
    "Other settings pages": [
        "SET-NAV", "SET-PREFERENCES", "SET-APPEARANCE", "SET-CARDS", "SET-HOME",
        "SET-DATA", "SET-ACCESS", "SET-NOTIFICATIONS", "SET-SYSTEM",
    ],
    "Sign-in, errors, onboarding": ["AUTH", "ONBOARDING", "ERRORS-DOCS"],
}


def register_statuses() -> dict[str, str]:
    """Read explicit component statuses."""
    text = (ROOT / "docs/ui/component-register.md").read_text()
    parts = re.split(r"^### ([A-Z][A-Z0-9_-]*) — .*$", text, flags=re.MULTILINE)
    statuses = {}
    for i in range(1, len(parts), 2):
        match = re.search(r"^- Status: `([^`]+)`", parts[i + 1], re.MULTILINE)
        statuses[parts[i]] = match.group(1) if match else "(no status)"
    return statuses


def register_counts() -> dict[str, int]:
    """Count each status."""
    counts: dict[str, int] = {}
    for status in register_statuses().values():
        counts[status] = counts.get(status, 0) + 1
    return counts


def register_score(entries=None) -> tuple[float, int]:
    """Credit earned and number of scored entries (Existing/no-UI-work entries excluded)."""
    statuses = register_statuses()
    scored = [e for e in (entries or statuses) if statuses.get(e) in CREDIT]
    return sum(CREDIT[statuses[e]] for e in scored), len(scored)


def area_scores() -> dict[str, tuple[float, int]]:
    """Calculate the register score by area."""
    statuses = register_statuses()
    placed = [e for entries in AREAS.values() for e in entries]
    if sorted(placed) != sorted(statuses):
        message = f"AREAS do not match the register: {sorted(set(placed) ^ set(statuses))}"
        raise SystemExit(message)
    return {area: register_score(entries) for area, entries in AREAS.items()}


def tag_sites() -> dict[str, tuple[int, int]]:
    """``{tag: (sites, templates)}`` for the atom tags: ``{% spinner %}`` and friends."""
    result = {}
    for tag in ATOM_TAGS:
        pattern = re.compile(r"\{%-?\s*" + tag + r"\b")
        counts = [len(pattern.findall(p.read_text(errors="ignore"))) for p in template_files()]
        result[tag] = (sum(counts), sum(1 for c in counts if c))
    return result


def button_census() -> dict[str, int]:
    """Hand-written ``<button>`` tags: all, Alpine-bound, and solid indigo or red."""
    open_tag = re.compile(r"<button\b[^>]*>", re.DOTALL)
    alpine = re.compile(r"(?:@click|x-on:click|x-show|:class|:disabled|x-bind)")
    solid = re.compile(r'class="[^"]*(?<![:\w-])bg-(?:indigo|red)-\d+(?![\w-])')
    total = bound = solid_tags = 0
    solid_files = set()
    for path in template_files():
        for tag in open_tag.findall(path.read_text(errors="ignore")):
            total += 1
            bound += bool(alpine.search(tag))
            if solid.search(tag):
                solid_tags += 1
                solid_files.add(path)
    return {
        "button_tags": total,
        "button_tags_alpine_bound": bound,
        "button_tags_solid_indigo_or_red": solid_tags,
        "templates_with_solid_buttons": len(solid_files),
    }


def entry_islands(markers: list[str]) -> dict[str, dict[str, int]]:
    """For each register entry: React islands its own mapped templates mount directly.

    Ownership comes from docs/ui/source-map.md. Only markers and tags written in the
    entry's own templates are counted, so an entry that merely includes a shared card
    shows that card here but is still ``Legacy`` unless it owns React code.
    """
    marker_re = re.compile("|".join(re.escape(m) for m in markers))
    tags = tag_re(ISLAND_TAGS)
    source_map = (ROOT / "docs/ui/source-map.md").read_text()
    sections = re.split(r"^## ([A-Z][A-Z0-9_-]*)$", source_map, flags=re.MULTILINE)
    result: dict[str, dict[str, int]] = {}
    for i in range(1, len(sections), 2):
        found: dict[str, int] = {}
        for rel in re.findall(r"`src/templates/([^`]+\.html)`", sections[i + 1]):
            path = TEMPLATES / rel
            if not path.exists():
                continue
            text = path.read_text(errors="ignore")
            for hit in set(marker_re.findall(text)) | set(tags.findall(text)):
                name = hit.removeprefix("data-").removesuffix("-root").replace("_", "-")
                found[name] = found.get(name, 0) + 1
        result[sections[i]] = found
    return result


# Patterns for the "how far would a shared component reach" counts. Each is a hand-written
# markup pattern a shared component could replace; the number is (matches, templates).
REACH = {
    "Icons (an included SVG or the icon tag)": r"""\{%-?\s*(?:include\s+["']app/icons/[^"']+["']|icon\s)""",
    "Section headings (h2 or h3 with text-lg or text-xl and font-semibold)": None,
    "Page titles (h1)": r"<h1\b",
    "Form fields (input other than hidden, checkbox, radio, submit, button, or textarea)": None,
    "Native select": r"<select\b",
    "Hand-rolled dropdowns (click-outside or click-away handler)": r"@click\.(?:outside|away)|x-on:click\.(?:outside|away)",
    "Notice boxes (role alert or status, or a tinted semantic background)": None,
    "Empty states ({% empty %} or a No ... found, yet or available message)": None,
}


def reach_counts() -> dict[str, tuple[int, int]]:
    """Count common template patterns."""
    heading = re.compile(r"<h[23]\b[^>]*class=\"[^\"]*(?=[^\"]*\btext-(?:lg|xl)\b)(?=[^\"]*\bfont-semibold\b)")
    field = re.compile(r"<textarea\b|<input\b(?![^>]*\btype=[\"'](?:hidden|checkbox|radio|submit|button)[\"'])", re.DOTALL)
    notice = re.compile(
        r"""role=["'](?:alert|status)["']|class="[^"]*\bbg-(?:red|amber|yellow|green|emerald|blue|sky|indigo)-\d{2,3}/\d{2}""",
    )
    empty = re.compile(r"\{%-?\s*empty\s*-?%\}|\bNo [A-Za-z ]{2,40}(?:found|yet|available)\b")
    special = {
        "Section headings (h2 or h3 with text-lg or text-xl and font-semibold)": heading,
        "Form fields (input other than hidden, checkbox, radio, submit, button, or textarea)": field,
        "Notice boxes (role alert or status, or a tinted semantic background)": notice,
        "Empty states ({% empty %} or a No ... found, yet or available message)": empty,
    }
    result = {}
    for name, pattern in REACH.items():
        regex = special.get(name) or re.compile(pattern)
        counts = [len(regex.findall(p.read_text(errors="ignore"))) for p in template_files()]
        result[name] = (sum(counts), sum(1 for c in counts if c))
    return result


# Browser-only APIs: a file that touches these cannot run unchanged on iOS or Android.
WEB_API_RE = re.compile(
    r"\b(window\.|document\.|htmx|localStorage|sessionStorage|navigator\.|location\.|"
    r"addEventListener|querySelector|classList|getBoundingClientRect|IntersectionObserver|"
    r"ResizeObserver|CustomEvent|FormData\b|fetch\()"
)

def is_web_adapter(path: Path, text: str) -> bool:
    """Mount points and island loaders are web adapters, unless they draw UI.

    A ``mount*.jsx`` that sets ``className`` is presentation that happens to live in
    a mount file (the bulk toolbar and dock), so it counts as presentation.
    """
    named = path.name.startswith("mount") or path.name in {"web.jsx", "index.js"}
    return named and "className=" not in text


def native_readiness() -> dict[str, dict]:
    """Classify every React presentation file for native reuse.

    ``rn`` files import ``react-native`` (rendered by react-native-web in the browser).
    ``dom`` files write HTML tags with CSS class names and cannot run on a phone as is.
    A file is ``clean`` when it also has no browser-only API reference. Web adapters
    (mount points that draw nothing, the loader) are listed but left out of the shares.
    """
    out = {}
    web_adapters = json.loads((ROOT / "docs/ui/architecture-registry.json").read_text()).get("web_adapters", {})
    for path in sorted(p for p in (ROOT / "frontend").rglob("*") if p.suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}):
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        adapter = rel in web_adapters or is_web_adapter(path, text)
        uses_rn = "from 'react-native'" in text or 'from "react-native"' in text
        out[rel] = {
            "lines": text.count("\n") + 1,
            "kind": "adapter" if adapter else ("rn" if uses_rn else "dom"),
            "web_api_refs": len(WEB_API_RE.findall(text)),
            "class_names": len(re.findall(r"className=", text)),
        }
    return out


def native_summary() -> dict[str, object]:
    """Summarize static candidates and recorded verification separately."""
    files = native_readiness()
    pres = {rel: d for rel, d in files.items() if d["kind"] != "adapter"}
    rn = {rel: d for rel, d in pres.items() if d["kind"] == "rn"}
    clean = {rel: d for rel, d in rn.items() if d["web_api_refs"] == 0 and d["class_names"] == 0}
    lines = sum(d["lines"] for d in pres.values())
    registry = json.loads((ROOT / "docs/ui/architecture-registry.json").read_text())
    entries = registry["universal"].values()
    components = [(component, entry["verification"]) for entry in entries for component in entry["components"]]
    return {
        "native_presentation_files": len(pres),
        "native_presentation_lines": lines,
        "native_rn_files": len(rn),
        "native_rn_lines": sum(d["lines"] for d in rn.values()),
        "native_rn_line_share": round(sum(d["lines"] for d in rn.values()) / lines, 4) if lines else 0,
        "native_clean_rn_files": len(clean),
        "native_registered_candidates": len(components),
        "native_ios_verified_components": sum(v["ios"]["status"] == "verified" for _, v in components),
        "native_android_verified_components": sum(v["android"]["status"] == "verified" for _, v in components),
        "native_verified_components": sum(v["ios"]["status"] == v["android"]["status"] == "verified" for _, v in components),
        "legacy_frozen_files": len(registry["legacy"]),
        "web_integration_adapters": len(registry.get("web_adapters", {})),
        "native_clean_rn_line_share": round(sum(d["lines"] for d in clean.values()) / lines, 4) if lines else 0,
        "native_dom_files": len(pres) - len(rn),
        "native_web_api_refs": sum(d["web_api_refs"] for d in pres.values()),
        "native_class_name_uses": sum(d["class_names"] for d in pres.values()),
    }


def main() -> int:
    """Print the selected report."""
    markers = loader_markers()
    if "--reach" in sys.argv:
        for name, (matches, files) in reach_counts().items():
            print(f"{name}: {matches} matches in {files} templates")
        return 0
    if "--areas" in sys.argv:
        if any(status not in CREDIT and status != "Existing (no UI work needed)" for status in register_statuses().values()):
            message = "Register statuses need reconciliation before area scores can be calculated."
            raise SystemExit(message)
        for area, (credit, count) in area_scores().items():
            print(f"{area}: {credit:g} of {count} = {credit / count:.0%}")
        return 0
    if "--native" in sys.argv:
        registry = json.loads((ROOT / "docs/ui/architecture-registry.json").read_text())
        for rel, d in native_readiness().items():
            classification = next((name for key, name in (("universal", "universal"), ("logic", "logic"), ("platform", "platform"), ("web_adapters", "web adapter")) if rel in registry.get(key, {})), "legacy")
            print(f"{classification:10} {d['lines']:5} lines  web-API refs {d['web_api_refs']:3}  className {d['class_names']:3}  {rel}")
        summary = native_summary()
        print(f"Candidates: {summary['native_registered_candidates']}; iOS verified: {summary['native_ios_verified_components']}; Android verified: {summary['native_android_verified_components']}; both: {summary['native_verified_components']}")
        return 0
    if "--entries" in sys.argv:
        for entry_id, found in entry_islands(markers).items():
            print(f"{entry_id}: {found or '-'}")
        return 0
    info = hosting(markers)
    big_markers = [m for m in markers if m not in ATOM_MARKERS]
    big = hosting(big_markers, tuple(t for t in ISLAND_TAGS if t not in ATOM_TAGS))
    big_hosts = sorted(rel for rel, d in big.items() if d["hosts"])
    total = len(info)
    hosts = sorted(rel for rel, d in info.items() if d["hosts"])
    host_lines = sum(info[rel]["lines"] for rel in hosts)
    all_lines = sum(d["lines"] for d in info.values())
    size = code_size()
    legacy_ui = size["template_lines"] + size["first_party_js_lines"]
    code_share = size["react_total_lines"] / (size["react_total_lines"] + legacy_ui)
    unclassified = [status for status in register_statuses().values()
                    if status not in CREDIT and status != "Existing (no UI work needed)"]
    report = {
        "loader_markers": len(markers),
        "register": register_counts(),
        "register_credit": register_score()[0],
        "register_scored_entries": register_score()[1],
        "register_weighted_share": None if unclassified else round(register_score()[0] / register_score()[1], 4),
        "register_unclassified_entries": len(unclassified),
        "templates_total": total,
        "templates_hosting_island": len(hosts),
        "templates_hosting_direct": sum(1 for rel in hosts if info[rel]["direct"]),
        "templates_hosting_via_include": sum(1 for rel in hosts if not info[rel]["direct"]),
        "template_host_share": round(len(hosts) / total, 4),
        "templates_hosting_substantive_island": len(big_hosts),
        "substantive_host_share": round(len(big_hosts) / total, 4),
        "substantive_host_lines": sum(big[rel]["lines"] for rel in big_hosts),
        "substantive_host_line_share": round(sum(big[rel]["lines"] for rel in big_hosts) / all_lines, 4),
        "host_template_lines": host_lines,
        "all_template_lines": all_lines,
        "host_line_share": round(host_lines / all_lines, 4),
        "atom_tag_sites_and_templates": tag_sites(),
        **button_census(),
        **size,
        "react_share_of_ui_code": round(code_share, 4),
        **native_summary(),
    }
    if "--json" in sys.argv:
        report["hosting_templates"] = hosts
        print(json.dumps(report, indent=2))
        return 0
    for key, value in report.items():
        print(f"{key}: {value}")
    if "--templates" in sys.argv:
        print("\n".join(hosts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
