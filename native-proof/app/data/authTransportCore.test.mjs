import assert from 'node:assert/strict';
import test from 'node:test';
import {
  AUTH_ERROR_CODES,
  AuthError,
  createAuthTransport,
  normalizeServerUrl,
} from './authTransportCore.js';

function response({ status = 200, body = null, setCookie = [] } = {}) {
  const text = body === null ? '' : typeof body === 'string' ? body : JSON.stringify(body);
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: {
      get: name => (String(name).toLowerCase() === 'set-cookie' ? setCookie.join(', ') : ''),
      getSetCookie: () => setCookie,
    },
    text: async () => text,
  };
}

function createFetch(routes) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    const route = routes.find(entry => entry.match(url, options));
    if (!route) throw new Error(`No route for ${options.method || 'GET'} ${url}`);
    return route.respond(url, options, calls);
  };
  return { fetchImpl, calls };
}

function createStorage() {
  const values = new Map();
  return {
    values,
    async getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    async setItem(key, value) {
      values.set(key, value);
    },
    async removeItem(key) {
      values.delete(key);
    },
  };
}

function sessionRoutes({ loginStatus = 302, sessionid = 'session-1', loginBody = null, verifyStatus = 200 } = {}) {
  return [
    {
      match: (url, options) => url.endsWith('/login/') && (options.method || 'GET') === 'GET',
      respond: () => response({ setCookie: ['csrftoken=csrf-1; Path=/; SameSite=Lax'] }),
    },
    {
      match: (url, options) => url.endsWith('/accounts/login/') && options.method === 'POST',
      respond: () => response({
        status: loginStatus,
        body: loginBody,
        setCookie: sessionid ? [`sessionid=${sessionid}; Path=/; HttpOnly`, 'csrftoken=csrf-2; Path=/'] : [],
      }),
    },
    {
      match: url => url.endsWith('/api/v1/user/sidebar/'),
      respond: () => response({ status: verifyStatus, body: verifyStatus === 200 ? { media_types: {} } : { detail: 'Invalid token' } }),
    },
  ];
}

test('normalizes server addresses and rejects credentials in the URL', () => {
  assert.equal(normalizeServerUrl('floppy.example'), 'https://floppy.example');
  assert.equal(normalizeServerUrl(' https://floppy.example/ '), 'https://floppy.example');
  assert.equal(normalizeServerUrl('http://floppy.example:8000/base/'), 'http://floppy.example:8000/base');
  assert.throws(() => normalizeServerUrl(''), AuthError);
  assert.throws(() => normalizeServerUrl('ftp://floppy.example'), AuthError);
  assert.throws(() => normalizeServerUrl('https://user:pass@floppy.example'), AuthError);
  assert.throws(() => normalizeServerUrl('https://floppy.example/?token=abc'), AuthError);
});

test('token sign-in verifies the credential and keeps the token out of public state', async () => {
  const storage = createStorage();
  const { fetchImpl, calls } = createFetch([
    { match: url => url.endsWith('/api/v1/user/sidebar/'), respond: () => response({ body: { media_types: {} } }) },
    { match: url => url.includes('/api/v1/lists/'), respond: () => response({ body: { results: [] } }) },
  ]);
  const changes = [];
  const auth = createAuthTransport({ storage, fetchImpl, onSessionChange: session => changes.push(session) });

  const state = await auth.signInWithToken({ serverUrl: 'https://floppy.example/', token: 'Bearer secret-token' });
  assert.equal(state.status, 'authenticated');
  assert.equal(state.hasCredential, true);
  assert.equal(JSON.stringify(state).includes('secret-token'), false);
  assert.equal(calls[0].options.headers.Authorization, 'Bearer secret-token');
  assert.equal(JSON.parse(storage.values.get('floppy.auth.session.v1')).token, 'secret-token');
  assert.equal(changes.at(-1).serverUrl, 'https://floppy.example');
  assert.equal('token' in changes.at(-1), false);

  const data = await auth.request('/api/v1/lists/', { query: { limit: 1 } });
  assert.deepEqual(data, { results: [] });
  assert.equal(calls[1].url, 'https://floppy.example/api/v1/lists/?limit=1');
});

test('a rejected token is reported as revoked, not as a missing session', async () => {
  const storage = createStorage();
  const { fetchImpl } = createFetch([
    { match: url => url.endsWith('/api/v1/user/sidebar/'), respond: () => response({ body: { media_types: {} } }) },
    { match: url => url.endsWith('/api/v1/lists/'), respond: () => response({ status: 401, body: { detail: 'Invalid token' } }) },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });
  await auth.signInWithToken({ serverUrl: 'https://floppy.example', token: 'secret-token' });

  await assert.rejects(() => auth.request('/api/v1/lists/'), error => {
    assert.equal(error.code, AUTH_ERROR_CODES.REVOKED);
    assert.equal(error.message.includes('secret-token'), false);
    return true;
  });
  assert.equal(auth.getState().status, 'revoked');
  assert.equal(storage.values.has('floppy.auth.session.v1'), false);
});

test('session sign-in sends CSRF and stores only the session cookies', async () => {
  const storage = createStorage();
  const routes = sessionRoutes();
  routes.push({
    match: url => url.endsWith('/api/v1/media/movie/'),
    respond: () => response({ body: { id: 1 } }),
  });
  const { fetchImpl, calls } = createFetch(routes);
  const auth = createAuthTransport({ storage, fetchImpl });

  const state = await auth.signIn({
    serverUrl: 'https://floppy.example',
    username: 'nova',
    password: 'hunter2-do-not-store',
  });
  assert.equal(state.status, 'authenticated');
  const loginCall = calls.find(call => call.options.method === 'POST');
  const body = new URLSearchParams(callbody(loginCall));
  assert.equal(body.get('login'), 'nova');
  assert.equal(body.get('password'), 'hunter2-do-not-store');
  assert.equal(body.get('csrfmiddlewaretoken'), 'csrf-1');
  assert.match(loginCall.options.headers.Cookie, /csrftoken=csrf-1/);
  assert.equal(loginCall.options.headers['X-CSRFToken'], 'csrf-1');

  const stored = [...storage.values.values()].join('\n');
  assert.match(stored, /sessionid=session-1/);
  assert.equal(stored.includes('hunter2-do-not-store'), false);

  await auth.request('/api/v1/media/movie/', { method: 'POST', body: { score: 8 } });
  const requestCall = calls.at(-1);
  assert.match(requestCall.options.headers.Cookie, /sessionid=session-1/);
  assert.match(requestCall.options.headers.Cookie, /csrftoken=csrf-2/);
  assert.equal(requestCall.options.headers['X-CSRFToken'], 'csrf-2');
  assert.equal(requestCall.options.credentials, 'include');
});

function callbody(call) {
  return call.options.body;
}

test('expired CSRF is refreshed once and the write is retried', async () => {
  const storage = createStorage();
  let writes = 0;
  const routes = [
    {
      match: (url, options) => url.endsWith('/login/') && (options.method || 'GET') === 'GET' && writes > 0,
      respond: () => response({ setCookie: ['csrftoken=csrf-3; Path=/'] }),
    },
    ...sessionRoutes(),
    {
      match: (url, options) => url.endsWith('/api/v1/media/movie/') && options.method === 'POST',
      respond: () => {
        writes += 1;
        if (writes === 1) return response({ status: 403, body: 'CSRF verification failed.' });
        return response({ body: { id: 1 } });
      },
    },
  ];
  const { fetchImpl, calls } = createFetch(routes);
  const auth = createAuthTransport({ storage, fetchImpl });
  await auth.signIn({ serverUrl: 'https://floppy.example', username: 'nova', password: 'secret' });

  const data = await auth.request('/api/v1/media/movie/', { method: 'POST', body: { score: 8 } });
  assert.deepEqual(data, { id: 1 });
  assert.equal(writes, 2);
  const lastWrite = calls.filter(call => call.url.endsWith('/api/v1/media/movie/')).at(-1);
  assert.equal(lastWrite.options.headers['X-CSRFToken'], 'csrf-3');
  assert.equal(auth.getState().status, 'authenticated');
});

test('wrong credentials stay signed out and persist nothing', async () => {
  const storage = createStorage();
  const { fetchImpl } = createFetch(sessionRoutes({ sessionid: '', verifyStatus: 401 }));
  const auth = createAuthTransport({ storage, fetchImpl });

  await assert.rejects(
    () => auth.signIn({ serverUrl: 'https://floppy.example', username: 'nova', password: 'wrong' }),
    error => error.code === AUTH_ERROR_CODES.INVALID_CREDENTIALS,
  );
  assert.equal(auth.getState().status, 'signed_out');
  assert.equal(storage.values.size, 0);
});

test('connection tests separate reachability from authentication', async () => {
  const storage = createStorage();
  const { fetchImpl } = createFetch([
    { match: url => url.endsWith('/ping/'), respond: () => response({ body: { status: 'ok' } }) },
    { match: url => url.endsWith('/api/v1/user/sidebar/'), respond: () => response({ body: { media_types: {} } }) },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });

  assert.deepEqual(
    await auth.testConnection({ serverUrl: 'floppy.example' }),
    { reachable: true, authenticated: false, serverUrl: 'https://floppy.example', user: null },
  );
  const authed = await auth.testConnection({ serverUrl: 'floppy.example', token: 'token-1' });
  assert.equal(authed.authenticated, true);
});

test('network failures become a safe connection error', async () => {
  const auth = createAuthTransport({
    storage: createStorage(),
    fetchImpl: async () => { throw new TypeError('Network request failed at https://example/secret'); },
  });
  await assert.rejects(
    () => auth.testConnection({ serverUrl: 'https://floppy.example' }),
    error => {
      assert.equal(error.code, AUTH_ERROR_CODES.SERVER_UNREACHABLE);
      assert.equal(error.message.includes('secret'), false);
      return true;
    },
  );
});

test('server detail is redacted before it reaches an error message', async () => {
  const storage = createStorage();
  const { fetchImpl } = createFetch([
    { match: url => url.endsWith('/api/v1/user/sidebar/'), respond: () => response({ body: { media_types: {} } }) },
    { match: url => url.endsWith('/api/v1/media/movie/'), respond: () => response({ status: 400, body: { detail: 'Bad token secret-token' } }) },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });
  await auth.signInWithToken({ serverUrl: 'https://floppy.example', token: 'secret-token' });

  await assert.rejects(() => auth.request('/api/v1/media/movie/'), error => {
    assert.equal(error.message.includes('secret-token'), false);
    assert.match(error.message, /\[redacted\]/);
    return true;
  });
});

test('restore exposes a request facade without leaking stored credentials', async () => {
  const storage = createStorage();
  const stored = {
    version: 1,
    serverUrl: 'https://floppy.example',
    authType: 'token',
    token: 'stored-token',
    user: { username: 'nova' },
  };
  storage.values.set('floppy.auth.session.v1', JSON.stringify(stored));
  const { fetchImpl, calls } = createFetch([
    { match: url => url.includes('/api/v1/lists/'), respond: () => response({ body: { results: [] } }) },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });

  assert.equal((await auth.restore()).status, 'authenticated');
  const facade = auth.getSession();
  assert.equal(facade.serverUrl, 'https://floppy.example');
  assert.equal(JSON.stringify(facade).includes('stored-token'), false);
  await facade.request('/api/v1/lists/');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer stored-token');
});
