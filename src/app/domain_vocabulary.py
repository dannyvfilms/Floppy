"""Approved Floppy domain terms and their documentation renderers."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainTerm:
    """Define one approved domain term."""

    key: str
    term: str
    definition: str
    bounded_context: str
    aliases: tuple[str, ...]
    relationships: tuple[tuple[str, str], ...]
    schema_org: str | None = None


DOMAIN_TERMS: tuple[DomainTerm, ...] = (
    DomainTerm(
        key="item",
        term="Item",
        definition=(
            "An Item is the shared work that Floppy identifies from a media provider. "
            "Users can track the same Item with separate Consumption records."
        ),
        bounded_context="app",
        aliases=("work",),
        relationships=(
            ("has user tracking record", "consumption"),
            ("is classified by", "media_type"),
        ),
        schema_org="https://schema.org/CreativeWork",
    ),
    DomainTerm(
        key="consumption",
        term="Consumption",
        definition=(
            "A Consumption is one user's tracking record for an Item. "
            "It stores the user's status, progress, score, dates, and notes."
        ),
        bounded_context="app",
        aliases=("tracking record", "media entry"),
        relationships=(("tracks", "item"),),
    ),
    DomainTerm(
        key="media_type",
        term="Media type",
        definition=(
            "A Media type classifies an Item. Canonical values come from "
            "`app.models.choices.MediaTypes`. API season and episode routes are nested "
            "under `tv`; season and episode are not top-level media types."
        ),
        bounded_context="app",
        aliases=("media kind",),
        relationships=(("classifies", "item"),),
    ),
    DomainTerm(
        key="celery_queue",
        term="Celery queue",
        definition=(
            "A Celery queue sends a task to a worker. Floppy uses the `celery`, "
            "`interactive`, and `discover` queue names. `celery` handles background "
            "work. `interactive` handles user-triggered work. `discover` handles "
            "Discover cache rebuilds. The Reload calendar task has no queue override, "
            "so it uses `celery` with background priority `9`."
        ),
        bounded_context="config",
        aliases=("task queue",),
        relationships=(("processes calendar updates for", "item"),),
    ),
)


def class_name(key: str) -> str:
    """Return the PascalCase JSON-LD class term for a vocabulary key."""
    return "".join(part.capitalize() for part in key.split("_"))


def property_name(relationship: str) -> str:
    """Return the camelCase JSON-LD property term for a relationship label."""
    head, *tail = relationship.split()
    return head.lower() + "".join(part.capitalize() for part in tail)


def validate_terms(terms: tuple[DomainTerm, ...]) -> None:
    """Reject ambiguous terms and unresolved relationships."""
    keys = [term.key.casefold() for term in terms]
    preferred_terms = [term.term.casefold() for term in terms]
    aliases = [alias.casefold() for term in terms for alias in term.aliases]

    if len(keys) != len(set(keys)):
        msg = "Domain term keys must be unique."
        raise ValueError(msg)
    if len(preferred_terms) != len(set(preferred_terms)):
        msg = "Preferred domain terms must be unique."
        raise ValueError(msg)
    if len(aliases) != len(set(aliases)):
        msg = "Domain term aliases must be unique."
        raise ValueError(msg)
    if set(preferred_terms) & set(aliases):
        msg = "A domain term alias cannot match a preferred term."
        raise ValueError(msg)

    resolved_keys = {term.key for term in terms}
    for term in terms:
        for _, target in term.relationships:
            if target not in resolved_keys:
                msg = f"Relationship target {target!r} does not resolve from {term.key!r}."
                raise ValueError(msg)

    # The JSON-LD context maps every relationship label to one property IRI, so
    # a collision across terms would silently collapse two relationships into
    # one. Check the *projected* property name, not the raw label: "has user"
    # and "Has  user" are different labels that both render as `hasUser`.
    properties = [
        property_name(relationship)
        for term in terms
        for relationship, _ in term.relationships
    ]
    if len(properties) != len(set(properties)):
        msg = "Domain relationship labels must render unique property names."
        raise ValueError(msg)


validate_terms(DOMAIN_TERMS)

GUIDE_PATH = Path(__file__).resolve().parents[2] / "docs" / "agents" / "domain_model.md"
GENERATED_WARNING = (
    "<!-- GENERATED FILE. DO NOT EDIT. Run "
    "`PYTHONPATH=src uv run --no-sync python -m app.domain_vocabulary` to regenerate. -->"
)

CONTEXT_PATH = Path(__file__).resolve().parents[1] / "api" / "contracts" / "context.jsonld"
FLOPPY_NAMESPACE = "https://github.com/dannyvfilms/Floppy/ns#"
SCHEMA_ORG_NAMESPACE = "https://schema.org/"


def render_glossary_rows() -> tuple[dict[str, str], ...]:
    """Return the approved fields needed by the API glossary template."""
    return tuple(
        {"key": term.key, "term": term.term, "definition": term.definition}
        for term in DOMAIN_TERMS
    )


def render_agent_guide() -> str:
    """Render the generated agent domain guide."""
    term_names = {term.key: term.term for term in DOMAIN_TERMS}
    lines = [
        GENERATED_WARNING,
        "",
        "# Floppy domain model",
        "",
        "Use these terms when you change Floppy or its API.",
    ]
    for term in DOMAIN_TERMS:
        lines.extend(
            (
                "",
                f"## {term.term}",
                "",
                term.definition,
                "",
                f"Bounded context: `{term.bounded_context}`.",
                "",
                "Aliases: " + ", ".join(f"`{alias}`" for alias in term.aliases) + ".",
                "",
                "Relationships:",
            )
        )
        lines.extend(
            f"- {relationship.capitalize()}: "
            f"[{term_names[target]}](#{target.replace('_', '-')})."
            for relationship, target in term.relationships
        )
        if term.schema_org:
            lines.extend(("", f"Schema.org type: `{term.schema_org}`."))

    return "\n".join(lines) + "\n"


def render_jsonld_context() -> str:
    """Render the JSON-LD 1.1 context from linked-data fields only.

    Reads ``key``, ``relationships``, and ``schema_org``. Definitions, aliases,
    and bounded contexts are prose and stay out of the linked-data artifact.
    """
    context: dict[str, object] = {
        "@version": 1.1,
        "@protected": True,
        "floppy": FLOPPY_NAMESPACE,
        "schema": SCHEMA_ORG_NAMESPACE,
    }
    for term in DOMAIN_TERMS:
        # A schema.org mapping makes the class term expand to the interoperable
        # IRI; otherwise it stays in Floppy's own namespace.
        context[class_name(term.key)] = (
            term.schema_org.replace(SCHEMA_ORG_NAMESPACE, "schema:")
            if term.schema_org
            else f"floppy:{term.key}"
        )
    for term in DOMAIN_TERMS:
        for relationship, _ in term.relationships:
            name = property_name(relationship)
            context[name] = {"@id": f"floppy:{name}", "@type": "@id"}

    return json.dumps({"@context": context}, indent=2, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the generated artifacts or check them for drift."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    artifacts = (
        (GUIDE_PATH, render_agent_guide().encode("utf-8")),
        (CONTEXT_PATH, render_jsonld_context().encode("utf-8")),
    )

    if args.check:
        return int(
            any(
                not path.exists() or path.read_bytes() != rendered
                for path, rendered in artifacts
            )
        )

    for path, rendered in artifacts:
        path.write_bytes(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
