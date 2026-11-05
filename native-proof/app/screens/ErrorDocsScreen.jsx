import React, { useState } from 'react';
import { Clipboard, Linking, StyleSheet, Text, View } from 'react-native';
import { ApiDocs } from '../../../frontend/errors/ApiDocs';
import { ErrorRecovery, ErrorStatusSelector } from '../../../frontend/errors/ErrorRecovery';
import { Screen } from '../components/Screen';
import { palette } from '../theme';

export const surface = {
  id: 'ERRORS-DOCS',
  status: 'in_progress',
  title: 'Errors and API docs',
  where: '400/403/CSRF/404/500 recovery, safe diagnostics and API documentation',
  note: 'Self-contained error recovery, copyable diagnostics and the API reference render with shared cards, chips, copy blocks and buttons. The browser error templates and API document remain the web fallback; no browser adapter is mounted. iOS and Android runtime are unverified.',
};

const docsPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  danger: palette.danger,
  focusStyle: {},
};

const docsBase = 'https://floppy.example.com';

function errorReport(status, title, message, extra, traceback) {
  return `Error: ${status} ${title}
Message: ${message}
${extra}Time (server): 2026-11-04T18:42:11+00:00
Method: GET
Path: /media/movie/
Full path: /media/movie/?page=2
URL: ${docsBase}/media/movie/?page=2
Host: floppy.example.com
Scheme: https
User: demo
Authenticated: yes
Session key present: yes
Origin: ${docsBase}
Referer: ${docsBase}/home
User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X)
Remote-Addr: 192.0.2.24
X-Forwarded-For: -
X-Forwarded-Proto: https

Traceback:
${traceback}`;
}

const errors = {
  400: {
    status: 400,
    heading: 'Bad Request',
    message: 'The server could not understand the request due to invalid syntax or missing parameters.',
    report: errorReport(400, 'Bad Request',
      'The server could not understand the request due to invalid syntax or missing parameters.',
      '',
      'Traceback unavailable.\nSuspiciousOperation: Broken payload\n  at app.views.media_list (src/app/views.py:412)\n  at django.core.handlers.exception (django/core/handlers/exception.py:59)'),
  },
  403: {
    status: 403,
    heading: 'Access Forbidden',
    message: "You don't have permission to access this resource. Please log in or contact an administrator.",
    checks: [
      "Confirm you're logged in and your session hasn't expired.",
      'Reload the page and try again.',
      "If you're using a PWA, open the site in Safari once to refresh cookies.",
    ],
    report: errorReport(403, 'Forbidden',
      "You don't have permission to access this resource. Please log in or contact an administrator.",
      '',
      'Traceback unavailable.\nPermissionDenied: Forbidden area\n  at app.views.protected_view (src/app/views.py:208)\n  at django.core.handlers.exception (django/core/handlers/exception.py:59)'),
  },
  csrf: {
    status: 403,
    heading: 'Access Forbidden',
    message: 'CSRF verification failed for this request. This usually means the CSRF cookie was missing, expired, or did not match the form token.',
    checks: [
      'Reload the page and try again.',
      "If you're using the iOS PWA, open the site in Safari once to refresh cookies.",
      "Confirm cookies are allowed and you're not switching between http and https or different domains.",
      'Admins: verify CSRF_TRUSTED_ORIGINS and URLS match the domain you use.',
    ],
    support: {
      title: 'Using a Reverse Proxy?',
      body: 'If you access Floppy through a reverse proxy, set the URLS environment variable to your application URL, for example https://floppy.mydomain.com.',
    },
    report: errorReport(403, 'Forbidden',
      'CSRF verification failed for this request. This usually means the CSRF cookie was missing, expired, or did not match the form token.',
      'Type: CSRF verification failed\nReason: CSRF token missing\nCSRF cookie present: no\n',
      'Traceback unavailable. Django rejected the request during CSRF validation before a view exception was raised.'),
  },
  404: {
    status: 404,
    heading: 'Page Not Found',
    message: "The page you are looking for doesn't exist or has been moved.",
    report: errorReport(404, 'Page Not Found',
      "The page you are looking for doesn't exist or has been moved.",
      '',
      'Traceback unavailable.\nHttp404: Missing object\n  at app.views.media_detail (src/app/views.py:634)\n  at django.core.handlers.exception (django/core/handlers/exception.py:59)'),
  },
  500: {
    status: 500,
    heading: 'Something Went Wrong',
    message: "We're sorry, but there was an error processing your request.",
    support: {
      title: 'Provider note',
      body: 'IGDB is not configured for this instance. Add the client credentials in provider settings, then try the request again. The traceback is unchanged and can be copied for a support ticket.',
      linkLabel: 'Open documentation',
      href: `${docsBase}/settings/providers/`,
    },
    report: errorReport(500, 'Server Error',
      "We're sorry, but there was an error processing your request.",
      '',
      'RuntimeError: Kaboom\n  at app.providers.igdb.fetch (src/app/providers/igdb.py:88)\n  at app.views.discover (src/app/views.py:1512)\n  at django.core.handlers.exception (django/core/handlers/exception.py:59)'),
  },
};

const statusOptions = [
  { value: '400', label: '400' },
  { value: '403', label: '403' },
  { value: 'csrf', label: '403 CSRF' },
  { value: '404', label: '404' },
  { value: '500', label: '500' },
];

const apiDocs = {
  intro: 'A read-only index for API setup and schema review. Use the same instance URL and an access token from Settings, then follow the verified contract.',
  tasks: [
    { label: 'Understand the domain model', href: `${docsBase}/api/docs/#domain-model` },
    { label: 'Make the first request', href: `${docsBase}/api/docs/#first-request` },
    { label: 'Open the full diagnostic schema', href: `${docsBase}/api/schema/` },
    { label: 'Open the verified API schema', href: `${docsBase}/api/openapi.yaml` },
  ],
  firstRequest: {
    intro: 'This public connectivity check needs no API token. For authenticated requests, copy your API Token in Settings -> Access & Tokens.',
    commands: [
      {
        caption: 'Check the connection',
        note: 'Public endpoint. No API token is needed.',
        command: `curl --request GET "${docsBase}/api/v1/info/"`,
      },
      {
        caption: 'Authenticated request',
        note: 'This read-only request returns your preferences.',
        command: `curl --request GET \\
  --header "X-API-Key: YOUR_API_TOKEN" \\
  "${docsBase}/api/v1/preferences/"`,
      },
    ],
  },
  workflows: {
    intro: 'Common recipes for searching, tracking, scrobbling and connecting AI coding assistants.',
    commands: [
      {
        caption: '1. Search the media catalog',
        command: `curl --request GET \\
  --header "X-API-Key: YOUR_API_TOKEN" \\
  "https://YOUR_FLOPPY_HOST/api/v1/search/movie/?search=Dune"`,
      },
      {
        caption: '2. Track or update media',
        command: `curl --request POST \\
  --header "X-API-Key: YOUR_API_TOKEN" \\
  --header "Content-Type: application/json" \\
  --data '{"title": "Dune", "status": 1, "score": 9}' \\
  "https://YOUR_FLOPPY_HOST/api/v1/media/movie/"`,
      },
      {
        caption: '3. Scrobble a music listen (ListenBrainz standard)',
        command: `curl --request POST \\
  --header "Authorization: Token YOUR_API_TOKEN" \\
  --header "Content-Type: application/json" \\
  --data '{"listen_type": "single", "payload": [{"listened_at": 1700000000, "track_metadata": {"artist_name": "Pink Floyd", "track_name": "Time", "release_name": "The Dark Side of the Moon"}}]}' \\
  "https://YOUR_FLOPPY_HOST/apis/listenbrainz/1/submit-listens/"`,
      },
      {
        caption: '4. Connect an AI assistant via FastMCP',
        command: 'claude mcp add floppy -- docker exec -i -e FLOPPY_TOKEN="YOUR_API_TOKEN" floppy uv run --no-sync python -m floppy_mcp',
      },
    ],
  },
  cheatSheet: [
    { category: 'System info', path: 'GET /api/v1/info/', description: 'Instance version, status and configuration.' },
    { category: 'Media entries', path: 'GET, POST /api/v1/media/{type}/', description: 'Query or create user media tracking records.' },
    { category: 'Item detail', path: 'GET, PATCH, DELETE /api/v1/media/{type}/{source}/{id}/', description: 'Manage an individual item status, score and progress.' },
    { category: 'Search', path: 'GET /api/v1/search/{type}/?search=...', description: 'Query provider catalog metadata.' },
    { category: 'History', path: 'GET /api/v1/history/', description: 'Chronological consumption events and scrobbles.' },
    { category: 'Lists', path: 'GET, POST /api/v1/lists/', description: 'Custom smart lists and curated collections.' },
    { category: 'List membership', path: 'PUT, DELETE /api/v1/media/{type}/{source}/{id}/lists/{list_id}/', description: 'Add or remove a title by provider id; unknown titles are created.' },
    { category: 'Collection', path: 'GET, POST /api/v1/collection/', description: 'Physical and digital media inventory tracking.' },
    { category: 'Collection by provider id', path: 'PUT, DELETE /api/v1/media/{type}/{source}/{id}/collection/', description: 'Mark a movie as owned. Episodes use the nested TV episode route.' },
    { category: 'Music plays', path: 'POST /api/v1/music/bulk-plays/', description: 'Batch log album tracks and plays.' },
    { category: 'Webhooks', path: 'POST /integrations/{service}/webhook/', description: 'Plex, Jellyfin, Emby, Kodi and Seerr sync.' },
  ],
  statusCodes: ['0 Planning', '1 In progress', '2 Paused', '3 Completed', '4 Dropped'],
  mediaTypes: ['movie', 'tv', 'anime', 'manga', 'book', 'comic', 'game', 'boardgame', 'music', 'podcast'],
  glossaryIntro: 'Use these terms when you read schema names and API responses.',
  glossary: [
    { term: 'Item', definition: 'The shared work that Floppy identifies from a media provider. Users can track the same Item with separate Consumption records.' },
    { term: 'Consumption', definition: "One user's tracking record for an Item. It stores status, progress, score, dates and notes." },
    { term: 'Media type', definition: 'Classifies an Item. Season and episode routes are nested under tv, not top-level media types.' },
    { term: 'Celery queue', definition: 'Routes a task to a worker. Floppy uses celery, interactive and discover queues; Reload calendar uses celery.' },
  ],
  schemasIntro: 'Open a schema from this instance. The diagnostic schema reflects the running code; the verified and domain contracts are committed artifacts.',
  schemas: [
    { title: 'Full diagnostic schema', badge: 'Live', description: 'Generated dynamically from this running Floppy instance. Use it for diagnostics.', href: `${docsBase}/api/schema/` },
    { title: 'Verified API subset', badge: 'YAML', description: 'The reviewed, committed and versioned subset for supported integrations and MCP grounding.', href: `${docsBase}/api/openapi.yaml` },
    { title: 'Domain context (JSON-LD)', badge: 'JSON-LD 1.1', description: "The JSON-LD 1.1 context types Floppy's domain nouns and maps them to schema.org where an equivalent exists.", href: `${docsBase}/api/context.jsonld` },
    { title: 'Asynchronous channels (AsyncAPI)', badge: 'AsyncAPI 3.0', description: 'The AsyncAPI 3.0 contract documents verified inbound message routes and Celery queue ownership.', href: `${docsBase}/api/asyncapi.json` },
  ],
};

export default function ErrorDocsScreen({ onBack }) {
  const [selected, setSelected] = useState('404');
  const [notice, setNotice] = useState('');
  const error = errors[selected];

  function copyText(text) {
    try {
      Clipboard.setString(text);
      return true;
    } catch {
      setNotice('Copy is unavailable on this device.');
      return false;
    }
  }

  async function openLink(entry) {
    const href = entry?.href;
    if (!href) {
      setNotice('This demo route stays inside the app shell.');
      return;
    }
    try {
      await Linking.openURL(href);
      setNotice(`Opening ${entry.label || entry.title || entry.href}`);
    } catch {
      setNotice('The link could not be opened on this device.');
    }
  }

  function retry() {
    setNotice('Retrying the request keeps the same path and query.');
  }

  function login() {
    setNotice('Log in, then reload the page that sent you here.');
  }

  return <Screen title="Errors" subtitle="Errors and API docs" onBack={onBack}>
    <ErrorStatusSelector options={statusOptions} selected={selected} onSelect={setSelected}
      palette={docsPalette} accessibilityLabel="Choose an error page example" />

    {notice ? <Text accessibilityLiveRegion="polite" style={[styles.notice, { color: palette.textMuted }]}>{notice}</Text> : null}

    <ErrorRecovery
      status={error.status}
      heading={error.heading}
      message={error.message}
      checks={error.checks}
      support={error.support ? {
        ...error.support,
        onOpen: () => openLink(error.support),
      } : undefined}
      report={error.report}
      labels={{ reportNote: 'Safe demo diagnostics. Copy this block when opening a ticket so the traceback and request details are preserved.' }}
      palette={docsPalette}
      onCopyReport={copyText}
      onReportIssue={() => openLink({ label: 'Report the issue', href: 'https://github.com/dannyvfilms/Floppy/issues' })}
      onRetry={selected === '500' ? retry : undefined}
      onLogin={selected === '403' || selected === 'csrf' ? login : undefined}
      onGoHome={onBack}
    />

    <View style={[styles.divider, { backgroundColor: palette.border }]} />
    <Text role="heading" aria-level={2} style={[styles.sectionTitle, { color: palette.text }]}>API documentation</Text>
    <ApiDocs model={apiDocs} palette={docsPalette} onOpenLink={openLink} onCopy={copyText} />
  </Screen>;
}

const styles = StyleSheet.create({
  notice: { fontSize: 12, lineHeight: 18 },
  divider: { height: 1, marginVertical: 4 },
  sectionTitle: { fontSize: 22, fontWeight: '700' },
});
