"""Find tracking writes that skip model signals.

Model signals refresh the library pages, Statistics and History after a single
``save()`` or ``delete()``. ``QuerySet.update``, ``bulk_create``,
``bulk_update``, raw SQL and blocks inside ``suppress_media_change_side_effects``
skip them, so each such site must refresh those readers itself.

This module parses the source tree once (``ast``, not text matching) and
returns one :class:`Site` per (module, function, model) that writes a tracker
model that way. ``app.tests.test_bulk_write_refresh`` compares the result with
``app.bulk_write_refresh.BULK_WRITE_SITES``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2]

# Code that never runs in production, or that only rewrites rows in place
# while the schema changes.
EXCLUDED_PARTS = frozenset({"tests", "migrations", "mock_data", "management"})
EXCLUDED_FILE_PREFIXES = ("test_",)
EXCLUDED_FILES = frozenset({"benchmark_data.py", "conftest.py"})

BULK_METHODS = frozenset({"bulk_create", "bulk_update"})
HISTORY_BULK_FUNCTIONS = frozenset(
    {"bulk_create_with_history", "bulk_update_with_history"}
)
UPDATE_METHODS = frozenset({"update", "_raw_delete"})
SUPPRESS_BLOCK = "suppress_media_change_side_effects"
SUPPRESS_MODEL = "<suppress_media_change_side_effects>"
UNRESOLVED_MODEL = "?"

# Managers a model exposes; reaching one names the model.
MANAGER_ATTRS = frozenset(
    {"objects", "_base_manager", "_default_manager", "all_objects"}
)
# QuerySet methods that return a QuerySet. A chain of these ending in
# ``.update()`` is a queryset write, even when the model is a variable.
QUERYSET_METHODS = frozenset(
    {
        "all",
        "filter",
        "exclude",
        "select_for_update",
        "order_by",
        "using",
        "distinct",
        "select_related",
        "prefetch_related",
        "only",
        "defer",
        "annotate",
        "none",
    }
)

SQL_WRITE_RE = re.compile(
    r"\b(?:update|insert\s+(?:or\s+\w+\s+)?into|delete\s+from)\s+[\"`]?app_(\w+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class Site:
    """One function that writes one tracker model without signals."""

    module: str
    function: str
    model: str
    line: int = 0
    kind: str = ""

    @property
    def key(self):
        return (self.module, self.function, self.model)


def tracker_model_names():
    """Return the class names of models that hold what a user tracks.

    Every ``Media`` subclass is included automatically, plus the play and
    tracker rows that carry dates, progress or status of their own.
    """
    from django.apps import apps

    from app.models import Media

    names = {
        model.__name__
        for model in apps.get_models(include_auto_created=False)
        if issubclass(model, Media)
    }
    names.update({"Media", "BasicMedia"})
    names.update(EXTRA_TRACKER_MODELS)
    return frozenset(names)


# Rows that are not ``Media`` but carry a user's plays, progress or status.
EXTRA_TRACKER_MODELS = frozenset(
    {
        "Episode",
        "MoviePlay",
        "VideoPlay",
        "PodcastPlay",
        "PodcastShowTracker",
        "BookListeningSession",
        "ArtistTracker",
        "AlbumTracker",
    }
)


def tracker_table_names(model_names):
    """Map ``app_<lowercase>`` table names back to model names."""
    return {f"{name.lower()}": name for name in model_names}


def _iter_source_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if EXCLUDED_PARTS.intersection(rel.parts[:-1]):
            continue
        if rel.name in EXCLUDED_FILES or rel.name.startswith(EXCLUDED_FILE_PREFIXES):
            continue
        if rel.parts[0] in {"node_modules", "staticfiles", "static"}:
            continue
        yield path, rel


def _terminal_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _string_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_string_text(node.left) or "") + (_string_text(node.right) or "")
    return None


class _FunctionScanner(ast.NodeVisitor):
    def __init__(self, module, trackers, tables):
        self.module = module
        self.trackers = trackers
        self.tables = tables
        self.stack = []
        # Per function: local name -> model name (or UNRESOLVED_MODEL) for
        # names bound to a queryset or manager.
        self.bindings = [{}]
        # Per function: local names bound to a string that writes SQL.
        self.sql_names = [{}]
        self.sites = []

    # -- scopes ---------------------------------------------------------

    def _qualname(self):
        return ".".join(self.stack) or "<module>"

    def _visit_scope(self, node):
        self.stack.append(node.name)
        self.bindings.append({})
        self.sql_names.append({})
        self.generic_visit(node)
        self.sql_names.pop()
        self.bindings.pop()
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_scope(node)

    def visit_ClassDef(self, node):
        self._visit_scope(node)

    def _add(self, model, node, kind):
        self.sites.append(
            Site(self.module, self._qualname(), model, getattr(node, "lineno", 0), kind)
        )

    # -- model resolution ----------------------------------------------

    def _resolve(self, node):
        """Return (is_queryset, model) for an expression.

        ``model`` is a tracker class name, another class name, or
        UNRESOLVED_MODEL when the expression is a queryset of unknown model.
        ``is_queryset`` is False when nothing marks the expression as a
        queryset or manager at all.
        """
        saw_queryset = False
        current = node
        while True:
            if isinstance(current, ast.Call) and isinstance(
                current.func, ast.Attribute
            ):
                if current.func.attr in QUERYSET_METHODS:
                    saw_queryset = True
                current = current.func.value
                continue
            if isinstance(current, ast.Attribute):
                if current.attr in MANAGER_ATTRS:
                    # ``model_cls.objects``, ``self.model.objects``,
                    # ``type(row).objects``: a variable, not a class name.
                    return True, _class_name(current.value)
                if current.attr.endswith("_set") or current.attr in {
                    "episodes",
                    "seasons",
                }:
                    return True, _related_model(current.attr) or UNRESOLVED_MODEL
                break
            if isinstance(current, ast.Name):
                bound = self.bindings[-1].get(current.id)
                if bound is not None:
                    return True, bound
                break
            break
        return saw_queryset, UNRESOLVED_MODEL

    def visit_Assign(self, node):
        self.generic_visit(node)
        is_queryset, model = self._resolve(node.value)
        text = _string_text(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                if is_queryset:
                    self.bindings[-1][target.id] = model
                else:
                    self.bindings[-1].pop(target.id, None)
                if text and SQL_WRITE_RE.search(text):
                    self.sql_names[-1][target.id] = text

    # -- writes ---------------------------------------------------------

    def visit_With(self, node):
        for item in node.items:
            expr = item.context_expr
            if (
                isinstance(expr, ast.Call)
                and _terminal_name(expr.func) == SUPPRESS_BLOCK
            ):
                self._add(SUPPRESS_MODEL, node, "suppress")
        self.generic_visit(node)

    def visit_Call(self, node):
        self.generic_visit(node)
        func = node.func
        name = _terminal_name(func)

        if name in HISTORY_BULK_FUNCTIONS:
            model_node = node.args[1] if len(node.args) > 1 else None
            for keyword in node.keywords:
                if keyword.arg == "model":
                    model_node = keyword.value
            self._add_if_tracker(_class_name(model_node), node, name)
            return

        if not isinstance(func, ast.Attribute):
            return

        if name in BULK_METHODS:
            _is_queryset, model = self._resolve(func.value)
            self._add_if_tracker(model, node, name)
            return

        if name in UPDATE_METHODS:
            is_queryset, model = self._resolve(func.value)
            if not is_queryset:
                return
            if name == "update" and node.args:
                # QuerySet.update takes keyword arguments only.
                return
            self._add_if_tracker(model, node, name)
            return

        if name in {"execute", "executemany"} and node.args:
            text = _string_text(node.args[0])
            if text is None and isinstance(node.args[0], ast.Name):
                text = self.sql_names[-1].get(node.args[0].id)
            for match in SQL_WRITE_RE.finditer(text or ""):
                model = self.tables.get(match.group(1).lower())
                if model:
                    self._add(model, node, "sql")

    def _add_if_tracker(self, model, node, kind):
        if model == UNRESOLVED_MODEL or model in self.trackers:
            self._add(model, node, kind)


def _class_name(node):
    """Return a class name, or UNRESOLVED_MODEL for a variable or call."""
    name = _terminal_name(node) if node is not None else None
    if not name or not name[0].isupper():
        return UNRESOLVED_MODEL
    return name


def _related_model(attr):
    """Name the model behind a related manager where the name says it."""
    if attr == "episodes":
        return "Episode"
    if attr == "seasons":
        return "Season"
    stem = attr.removesuffix("_set")
    return {
        "episode": "Episode",
        "season": "Season",
        "movie": "Movie",
        "tv": "TV",
        "anime": "Anime",
        "manga": "Manga",
        "game": "Game",
        "boardgame": "BoardGame",
        "book": "Book",
        "comic": "Comic",
        "music": "Music",
        "podcast": "Podcast",
        "podcastplay": "PodcastPlay",
        "movieplay": "MoviePlay",
    }.get(stem)


def scan(root: Path = SRC_ROOT, trackers=None):
    """Return every bulk tracking write site under ``root``, sorted."""
    trackers = trackers if trackers is not None else tracker_model_names()
    tables = tracker_table_names(trackers)
    sites = []
    for path, rel in _iter_source_files(root):
        source = path.read_text(encoding="utf-8")
        if not any(
            token in source
            for token in ("bulk_", ".update(", "_raw_delete", "execute", SUPPRESS_BLOCK)
        ):
            continue
        tree = ast.parse(source, filename=str(rel))
        scanner = _FunctionScanner(rel.as_posix(), trackers, tables)
        scanner.visit(tree)
        sites.extend(scanner.sites)
    return sorted(sites)


def site_keys(sites):
    """Collapse sites to the (module, function, model) keys the table uses."""
    return {site.key for site in sites}
