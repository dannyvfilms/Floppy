const BASE = '/api/v1/providers/';
const slugPath = (slug, suffix = '') => `${BASE}${encodeURIComponent(slug)}/${suffix}`;

const array = value => (Array.isArray(value) ? value : []);

// The directory endpoint returns the shared directory model (filters, options,
// items). Each item carries its connection status so the list shows health.
export function directoryFromPayload(payload) {
  const model = payload && typeof payload === 'object' ? payload : {};
  return {
    ...model,
    filters: { q: '', capability: '', media: '', ...(model.filters || {}) },
    capabilities: array(model.capabilities),
    media: array(model.media),
    items: array(model.items).filter(item => item && item.slug),
    canPin: model.canPin !== false,
  };
}

// The detail endpoint returns the shared provider page model plus the pieces
// the connection, import and activity bodies need. The shared page view renders
// bodies only when `contentOwner` is `react`, which native always is.
export function detailFromPayload(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const page = { ...(data.page || {}), contentOwner: 'react' };
  const connection = data.connection || {};
  return {
    slug: data.slug || '',
    page,
    state: data.state || {},
    pinned: Boolean(data.pinned),
    readOnly: Boolean(data.readOnly),
    connection,
    settingsModel: {
      tab: page.tab,
      labels: page.labels,
      credentials: data.credentials || undefined,
      account: connection.account || undefined,
      setupGuides: array(data.guides),
      guideCopy: data.guideCopy || {},
      guidesSessionRequired: Boolean(data.guidesSessionRequired),
    },
    schedules: array(data.schedules),
    activity: array(data.activity),
    importPreferences: data.importPreferences || null,
    fileImport: data.fileImport && typeof data.fileImport === 'object' ? data.fileImport : null,
    forms: data.forms && typeof data.forms === 'object' ? data.forms : {},
    canImport: Boolean(connection.canSchedule),
  };
}

export function importBody({ username, mode, frequency, time }) {
  const body = { user: String(username || '').trim() };
  if (mode) body.mode = mode;
  body.frequency = frequency || 'once';
  if (time) body.time = time;
  return body;
}

export function credentialsBody(kind, values) {
  const clean = {};
  for (const [name, value] of Object.entries(values || {})) {
    if (typeof value === 'string' && value.trim() !== '') clean[name] = value.trim();
  }
  return { scope: kind === 'personal' ? 'personal' : 'instance', values: clean };
}

export function createRemoteProvidersActions(request) {
  const send = (method, path, body) => request(path, { method, body: body === undefined ? {} : body });
  return {
    mode: 'server',
    directory: filters => request(BASE, { query: Object.fromEntries(Object.entries(filters || {}).filter(([, value]) => value)) }),
    detail: (slug, tab) => request(slugPath(slug), { query: tab ? { tab } : undefined }),
    pin: (slug, pinned) => send('POST', `${BASE}pin/`, { provider: slug, pinned: Boolean(pinned) }),
    connect: (slug, values) => send('POST', slugPath(slug, 'connect/'), values || {}),
    disconnect: (slug, body) => send('POST', slugPath(slug, 'disconnect/'), body || {}),
    metadataAction: (slug, body) => send('POST', slugPath(slug, 'metadata/'), body),
    startLink: (slug, body) => send('POST', slugPath(slug, 'connect/start/'), body || {}),
    pollLink: slug => request(slugPath(slug, 'connect/poll/')),
    cancelLink: slug => send('POST', slugPath(slug, 'connect/cancel/')),
    saveCredentials: (slug, kind, values) => send('PUT', slugPath(slug, 'credentials/'), credentialsBody(kind, values)),
    clearCredentials: slug => send('DELETE', slugPath(slug, 'credentials/')),
    importFile: (slug, { name, content, contentBase64, mode }) => send('POST', slugPath(slug, 'file-import/'), {
      name, mode, ...(contentBase64 ? { contentBase64 } : { content }),
    }),
    saveForm: (slug, key, values, tab) => send('POST', slugPath(slug, `forms/${encodeURIComponent(key)}/`), { tab, values }),
    test: (slug, instanceId) => send('POST', slugPath(slug, 'test/'), instanceId ? { instance_id: instanceId } : {}),
    sync: (slug, instanceId) => send('POST', slugPath(slug, 'sync/'), instanceId ? { instance_id: instanceId } : {}),
    importNow: (slug, form) => send('POST', slugPath(slug, 'import/'), importBody(form)),
    deleteSchedule: (slug, taskName) => send('DELETE', slugPath(slug, 'schedules/'), { task_name: taskName }),
  };
}

export function createLocalProvidersActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    directory: local,
    detail: local,
    pin: local,
    connect: local,
    disconnect: local,
    metadataAction: local,
    startLink: local,
    pollLink: local,
    cancelLink: local,
    saveCredentials: local,
    clearCredentials: local,
    saveForm: local,
    importFile: local,
    test: local,
    sync: local,
    importNow: local,
    deleteSchedule: local,
  };
}
