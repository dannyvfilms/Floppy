const BASE = '/api/v1/connections/';
const array = value => (Array.isArray(value) ? value : []);

export function connectionsFromPayload(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  return {
    accounts: array(data.accounts),
    sync: array(data.sync).map(row => ({
      ...row,
      capabilities: array(row.capabilities),
      direction_choices: array(row.direction_choices),
    })),
    conflicts: array(data.conflicts),
  };
}

export function deviceFromPayload(payload) {
  if (!payload || !payload.application) return null;
  return {
    userCode: String(payload.user_code || ''),
    application: String(payload.application),
    scopes: array(payload.scopes).map(scope => ({
      scope: scope.scope,
      label: scope.label || scope.scope,
      description: scope.description || '',
    })),
  };
}

export function createRemoteConnectionsActions(request) {
  const send = (method, path, body) => request(path, { method, body: body === undefined ? {} : body });
  return {
    mode: 'server',
    load: () => request(BASE),
    setDirection: (bindingId, direction) => send('POST', `${BASE}${encodeURIComponent(bindingId)}/direction/`, { direction }),
    setPaused: (bindingId, paused) => send('POST', `${BASE}${encodeURIComponent(bindingId)}/pause/`, { paused: Boolean(paused) }),
    resolveConflict: (conflictId, watched) => send('POST', `/api/v1/sync/conflicts/${encodeURIComponent(conflictId)}/resolve/`, { watched: Boolean(watched) }),
    lookupDevice: userCode => request(`${BASE}device/`, { query: { user_code: String(userCode || '').trim() } }),
    decideDevice: (userCode, action) => send('POST', `${BASE}device/`, { user_code: String(userCode || '').trim(), action }),
  };
}

export function createLocalConnectionsActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    load: local,
    setDirection: local,
    setPaused: local,
    resolveConflict: local,
    lookupDevice: local,
    decideDevice: local,
  };
}
