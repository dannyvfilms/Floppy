# Provider settings

Settings are organized around services rather than separate configuration
screens. `users.provider_catalog` declares each provider's supported
capabilities, media types and tabs. The directory at `/settings/providers`
combines search, capability and media-type filters. A provider's canonical page
is `/settings/providers/<slug>`, with `?tab=<tab>` selecting a section.

Tabs appear only when the provider supports their contents, in this order:
Overview, Connection, Metadata, Import, Tracking, Sync, Activity. File-only
imports have no Connection tab. A configured credential makes an operation
available; it does not mean that an import, intake rule or outbound sync is
enabled or healthy.

The directory uses the Import Data tile layout with shared source identities and
short descriptions. Detailed capability and setup state lives on provider pages. Its unboxed search and two dropdowns follow the Lists hub toolbar;
search and filters combine without replacing the toolbar. Credential and outbound
settings share a provider row.

The page shell reuses the existing forms, validation, action routes and jobs.
Credential setup does not silently enable capabilities. Existing combined
connect-and-import workflows disclose their immediate and recurring intake
before the setup action. Connection owns credentials and setup identity; Import owns historical
and recurring inbound pulls; Tracking owns event-driven intake; Sync owns
outbound writes from Floppy. A recurring import is still Import.

## Metadata source preferences

`users.metadata_views.metadata_context` builds credentials and source controls
for a provider. Credential storage and resolution stay in
`app.providers.credentials`; personal keys, instance-wide keys and environment
values retain their existing precedence and permission checks. Provider pages
do not render stored personal secrets or place them in navigation URLs. Connection
shows instance and personal fields inline; instance fields remain read-only for
non-superusers and when their values are set in the environment. The Read-only
badge explains access, and the key badge links to the provider or opens its
additional setup instructions when needed.

Metadata source cards share the existing user preference for each library type.
TV, anime, books and comics have a selectable default; other library types show
their supported sources without inventing a new preference. Changing a default
affects new titles. Existing library conversion and migration remain separate,
explicit operations with their existing data-safety warnings.

These preferences choose a single source. They are not an ordered fallback
list. User-managed ranking is deferred until the metadata backend supports that
contract. Supplemental artwork, artist biographies, popularity and critic
scores keep their own roles rather than competing with a library's primary
catalog source. Game artwork's role-specific fallback policy is described in
[Game artwork](game-artwork.md).

## Shared destinations and compatibility

Activity uses the existing import runs, schedules, sync results and matching
records. A provider's Activity tab scopes or links to those same records; it
does not introduce a second logging system.

Data Management contains file exports, backup restoration, imported-data
cleanup and library repair. Access & Tokens contains credentials and client
authorizations granting access to Floppy. Those authorizations are distinct
from credentials Floppy uses to access a provider.

Legacy settings URLs redirect to a provider tab, filtered directory or shared
destination and retain useful query parameters. Existing mutation endpoints
remain valid. Return destinations supplied by forms are validated with
`app.helpers.safe_return_url` before navigation.

When adding a capability, declare it from implemented behavior, reuse the
appropriate settings context and form, and check both its provider destination
and the existing action endpoint. Do not infer capability support from the
presence of an API key.
