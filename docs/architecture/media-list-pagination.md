# Media-list pagination

The media-list API SQL path is the reference for the web media-list route and
for list-detail pagination behavior.

## SQL-first path

When a request has a concrete media type, a database-sortable key, and only
SQL-safe filters, the tracker queryset applies item filters, latest-status
selection, duplicate-row selection, deterministic ordering, `COUNT`, and
`LIMIT/OFFSET` before media objects are hydrated. Ordering ends with the item
title and item ID tie-breakers so repeated requests cannot move equal-key
items between pages. Only the visible page is prefetched and duplicate-
aggregated.

Filter-menu metadata on a cold request comes from narrow `Item.values()`
projections and independent collection/tag lookups. It does not require
hydrating the complete tracker/media graph.

Grouped TV/anime entries and the podcast/music adapter surfaces remain on
their specialized pipelines. The root heterogeneous media endpoint is also
not SQL-paginated because merging different media models requires a separate
cross-model ordering contract.

## Python-only fallback

Filters and sorts that depend on derived progress, rating, collection state,
platform resolution, providers, authors, formats, or other Python semantics
still require an O(n) candidate scan. The scan is performed in fixed-size
batches: media graphs and duplicate aggregation are released after each
batch, while compact item IDs and sort keys are retained until the requested
page is known. The final page is then bulk-hydrated and prefetched.

This bounds model hydration and batch memory, but it does not make a Python
sort constant-time. Add a SQL expression or index only when query-plan and
benchmark evidence demonstrates that it preserves the existing semantics.
