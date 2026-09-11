# Plex and Trakt match corrections

This feature keeps provider identities separate from the Floppy item they were
matched to. Automatic title resolution accepts a result only when its
normalized title is unique, and an available year agrees; provider IDs remain
authoritative unless a saved correction or contradictory identity evidence
overrides them. A title search that is ambiguous, missing an ID, or only
matches by year is queued for review.

## Source identity contract

`ExternalReference` is user-scoped and keyed by integration, source account,
namespace, identity, and media type. Plex rating keys are scoped by Plex server
and account; Trakt IDs are scoped by the imported source account. Episode
identities stay episode identities, and Plex local IDs are never treated as
TMDB, TVDB, or IMDb IDs. Only display-safe metadata from the allowlist is
stored.

Saved corrections and ignores are checked before provider resolution by Plex
history imports, Plex webhooks, Plex watchlists, and Trakt API, archive, and
collection imports. Episode corrections retain an explicit source-to-
destination season/episode mapping. Removing a decision clears the override;
it does not rewrite historical provider data or invent missing provenance.

## Correction workflow

The TV/movie details action and the Integrations matching-review queue open the
same correction flow. It searches supported same-type TMDB destinations,
creates a preview of this user's tracking state, requires every affected
episode to be mapped, and applies the move and saved source decisions in one
transaction. A stale preview is rejected when concurrent user-owned state has
changed. Existing watch events are merged only when their external identity is
reliable; unidentified events are retained and scalar conflicts require an
explicit choice.

The move changes only relationships owned by the requesting user. It does not
edit Plex or Trakt, shared provider identities, or another user's data. A
historical item with no reliable source reference can still be moved, but the
UI does not promise that future imports will follow that move; the user must
re-upload a file import to resolve it through the normal import path.

## Upgrade guidance

Deploy the migrations on the current Floppy migration graph, including
`0045_external_references` and its generated follow-up migration. Run the
normal SQLite/PostgreSQL migration checks and `check_migration_hygiene
--strict`. Existing Plex watchlist rows retain their behavior with an empty
server scope; subsequent syncs populate the server/account scope. No
historical item is rewritten and no external identity is backfilled without a
new observation.
