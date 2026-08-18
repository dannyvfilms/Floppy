"""Plan and apply data-preserving SQLite foreign-key recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# These rows only describe a relationship between parent catalog records. If a
# required parent is gone, the relationship row has no independent user state.
_DERIVED_RELATION_TABLES = frozenset({"app_albumartist"})


class UnsafeRepairPlanError(ValueError):
    """Raised when a repair plan cannot be applied automatically."""


class UnsupportedRepairRelationshipError(ValueError):
    """Raised when a plan contains a relationship the executor cannot repair."""


class UnsupportedRepairActionError(ValueError):
    """Raised when a repair group names an action the executor does not support."""

    def __init__(self, action: object):
        super().__init__(f"unsupported repair action {action!r}")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _foreign_key_definition(
    conn: sqlite3.Connection,
    table: str,
    foreign_key_id: int,
) -> dict | None:
    rows = list(
        conn.execute(
            'SELECT id, seq, "table", "from", "to", on_update, on_delete, match '
            "FROM pragma_foreign_key_list(?, 'main') WHERE id = ? ORDER BY seq",
            [table, foreign_key_id],
        )
    )
    # Compound keys need coordinated multi-column repair. Do not guess.
    if len(rows) != 1 or rows[0][1] != 0:
        return None

    _id, _seq, parent, child_column, parent_column, _update, _delete, _match = rows[0]
    if not all(
        isinstance(value, str) and value
        for value in (parent, child_column, parent_column)
    ):
        return None

    column = conn.execute(
        'SELECT name, "notnull" FROM pragma_table_xinfo(?, \'main\') WHERE name = ?',
        [table, child_column],
    ).fetchone()
    if not column:
        return None

    return {
        "child_column": child_column,
        "nullable": not bool(column[1]),
        "parent": parent,
        "parent_column": parent_column,
    }


def build_repair_plan(conn: sqlite3.Connection, incident: dict) -> dict:
    """Classify each broken relationship by the least destructive repair."""
    groups = []
    unsupported = []
    safe_relationships = 0
    required_relationships = 0

    for group in incident.get("groups", []):
        table = str(group.get("table") or "")
        parent = str(group.get("parent") or "")
        foreign_key_id = int(group.get("foreign_key_id", -1))
        count = int(group.get("count", 0))
        definition = _foreign_key_definition(conn, table, foreign_key_id)

        if definition is None or definition["parent"] != parent:
            action = "manual"
            unsupported.append(
                f"{table or '<unknown>'} foreign key {foreign_key_id} "
                "cannot be repaired safely",
            )
            child_column = None
            parent_column = None
            automatic = False
        elif definition["nullable"]:
            action = "clear_reference"
            child_column = definition["child_column"]
            parent_column = definition["parent_column"]
            automatic = True
            safe_relationships += count
        elif table in _DERIVED_RELATION_TABLES:
            action = "remove_relationship"
            child_column = definition["child_column"]
            parent_column = definition["parent_column"]
            automatic = True
            safe_relationships += count
        else:
            action = "remove_row"
            child_column = definition["child_column"]
            parent_column = definition["parent_column"]
            automatic = False
            required_relationships += count

        groups.append(
            {
                "action": action,
                "automatic": automatic,
                "child_column": child_column,
                "count": count,
                "foreign_key_id": foreign_key_id,
                "parent": parent,
                "parent_column": parent_column,
                "table": table,
            }
        )

    technical_reasons = list(incident.get("unsafe_reasons", []))
    if not incident.get("can_quarantine", False):
        technical_reasons.append(
            "the affected table layout is not safe for automatic writes"
        )

    can_repair = not unsupported and not technical_reasons
    return {
        "can_repair": can_repair,
        "groups": groups,
        "required_relationships": required_relationships,
        "safe_relationships": safe_relationships,
        "unsupported_reasons": [*unsupported, *technical_reasons],
    }


def _broken_reference_where(group: dict) -> str:
    child = _quote_identifier(group["child_column"])
    parent_table = _quote_identifier(group["parent"])
    parent_column = _quote_identifier(group["parent_column"])
    # Identifiers come only from SQLite schema inspection and are quoted above;
    # no request, report, provider, or user value is interpolated here.
    return (  # noqa: S608
        f"{child} IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM main.{parent_table} AS parent "
        f"WHERE parent.{parent_column} = {child})"
    )


def apply_repair_plan(
    conn: sqlite3.Connection,
    plan: dict,
    *,
    include_required: bool,
) -> dict:
    """Apply the plan inside the caller's transaction and return actual counts."""
    if not plan.get("can_repair"):
        raise UnsafeRepairPlanError

    counts = {
        "references_cleared": 0,
        "relationship_rows_removed": 0,
        "required_rows_removed": 0,
    }

    for group in plan.get("groups", []):
        action = group["action"]
        if action == "manual":
            raise UnsupportedRepairRelationshipError
        if action == "remove_row" and not include_required:
            continue

        table = _quote_identifier(group["table"])
        where = _broken_reference_where(group)
        if action == "clear_reference":
            column = _quote_identifier(group["child_column"])
            result = conn.execute(
                f"UPDATE main.{table} SET {column} = NULL WHERE {where}"  # noqa: S608
            )
            counts["references_cleared"] += result.rowcount
        elif action == "remove_relationship":
            result = conn.execute(
                f"DELETE FROM main.{table} WHERE {where}"  # noqa: S608
            )
            counts["relationship_rows_removed"] += result.rowcount
        elif action == "remove_row":
            result = conn.execute(
                f"DELETE FROM main.{table} WHERE {where}"  # noqa: S608
            )
            counts["required_rows_removed"] += result.rowcount
        else:
            raise UnsupportedRepairActionError(action)

    return counts
