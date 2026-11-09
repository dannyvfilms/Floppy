import assert from 'node:assert/strict';
import test from 'node:test';
import {
  AUTH_ERROR_CODES,
  AuthError,
  buildDeviceVerificationUrl,
  buildProviderLoginUrl,
  createAuthTransport,
  normalizeServerUrl,
  safeRedirectPath,
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
      match: (url, options) => url.endsWith('/accounts/login/') && (options.method || 'GET') === 'GET',
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
  const csrfCall = calls.find(call => call.options.method === 'GET' && call.url.endsWith('/accounts/login/'));
  assert.ok(csrfCall, 'session sign-in asks the all-auth login page for a CSRF cookie');
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
      match: (url, options) => url.endsWith('/accounts/login/') && (options.method || 'GET') === 'GET' && writes > 0,
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


test('redirect intents stay on the server and reject unsafe paths', () => {
  assert.equal(safeRedirectPath('/library?tab=music#top'), '/library?tab=music#top');
  assert.equal(safeRedirectPath('//evil.example/path'), '/');
  assert.equal(safeRedirectPath('https://evil.example'), '/');
  assert.equal(safeRedirectPath('/\\evil'), '/');
  assert.equal(buildProviderLoginUrl({ serverUrl: 'floppy.example', providerId: 'trakt', redirectTo: '/home' }),
    'https://floppy.example/accounts/trakt/login/?process=login&next=%2Fhome');
  assert.throws(() => buildProviderLoginUrl({ serverUrl: 'floppy.example', providerId: '../evil' }), AuthError);
  assert.equal(buildDeviceVerificationUrl({ serverUrl: 'floppy.example', userCode: 'ABCD-EFGH' }),
    'https://floppy.example/oauth/device?user_code=ABCD-EFGH');
});

test('session cookie rotation is persisted after a write', async () => {
  const storage = createStorage();
  let rotated = false;
  const routes = [
    ...sessionRoutes(),
    {
      match: (url, options) => url.endsWith('/api/v1/media/movie/') && options.method === 'POST',
      respond: () => {
        rotated = true;
        return response({ body: { id: 1 }, setCookie: ['sessionid=session-2; Path=/; HttpOnly'] });
      },
    },
    {
      match: url => url.endsWith('/api/v1/lists/'),
      respond: () => response({ body: { results: [] } }),
    },
  ];
  const { fetchImpl, calls } = createFetch(routes);
  const auth = createAuthTransport({ storage, fetchImpl });
  await auth.signIn({ serverUrl: 'https://floppy.example', username: 'nova', password: 'secret' });
  await auth.request('/api/v1/media/movie/', { method: 'POST', body: { score: 8 } });
  assert.equal(rotated, true);
  const stored = JSON.parse(storage.values.get('floppy.auth.session.v1'));
  assert.equal(stored.cookies.sessionid, 'session-2');
  await auth.request('/api/v1/lists/');
  assert.match(calls.at(-1).options.headers.Cookie, /sessionid=session-2/);
});

test('verifying a stored session clears it when the server rejects it', async () => {
  const storage = createStorage();
  storage.values.set('floppy.auth.session.v1', JSON.stringify({
    version: 1,
    serverUrl: 'https://floppy.example',
    authType: 'session',
    cookies: { sessionid: 'session-1' },
    csrfToken: 'csrf-1',
    cookieText: 'sessionid=session-1; csrftoken=csrf-1',
    user: { username: 'nova' },
  }));
  const { fetchImpl } = createFetch([
    { match: url => url.endsWith('/api/v1/user/sidebar/'), respond: () => response({ status: 401, body: { detail: 'Session expired' } }) },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });
  assert.equal((await auth.restore()).status, 'authenticated');
  await assert.rejects(() => auth.verify(), error => error.code === AUTH_ERROR_CODES.EXPIRED);
  assert.equal(auth.getState().status, 'expired');
  assert.equal(storage.values.has('floppy.auth.session.v1'), false);
});

test('signup posts the native JSON request and stores only cookies', async () => {
  const storage = createStorage();
  const { fetchImpl, calls } = createFetch([
    {
      match: (url, options) => url.endsWith('/accounts/signup/') && (options.method || 'GET') === 'GET',
      respond: () => response({ setCookie: ['csrftoken=signup-csrf; Path=/'] }),
    },
    {
      match: (url, options) => url.endsWith('/accounts/signup/') && options.method === 'POST',
      respond: () => response({
        body: { ok: true },
        setCookie: ['sessionid=signup-session; Path=/; HttpOnly', 'csrftoken=signup-csrf-2; Path=/'],
      }),
    },
    { match: url => url.endsWith('/api/v1/user/sidebar/'), respond: () => response({ body: { media_types: {} } }) },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });
  const state = await auth.signUp({
    serverUrl: 'https://floppy.example',
    username: 'nova',
    password1: 'signup-secret',
    password2: 'signup-secret',
  });
  assert.equal(state.status, 'authenticated');
  const signupCall = calls.find(call => call.url.endsWith('/accounts/signup/') && call.options.method === 'POST');
  assert.equal(signupCall.options.headers['X-Floppy-Client'], 'native');
  assert.equal(signupCall.options.headers.Accept, 'application/json');
  const stored = [...storage.values.values()].join('\n');
  assert.match(stored, /sessionid=signup-session/);
  assert.equal(stored.includes('signup-secret'), false);
});

test('recovery reports server field errors without keeping the password', async () => {
  const storage = createStorage();
  const { fetchImpl } = createFetch([
    {
      match: (url, options) => url.endsWith('/accounts/password/recover/') && (options.method || 'GET') === 'GET',
      respond: () => response({ setCookie: ['csrftoken=recover-csrf; Path=/'] }),
    },
    {
      match: (url, options) => url.endsWith('/accounts/password/recover/') && options.method === 'POST',
      respond: () => response({ status: 400, body: { ok: false, errors: { non_field_errors: ['Unable to verify recovery details.'] } } }),
    },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });
  await assert.rejects(
    () => auth.recoverPassword({
      serverUrl: 'https://floppy.example',
      username: 'nova',
      recoveryCode: 'RECOVERY-CODE',
      newPassword1: 'recovery-secret',
      newPassword2: 'recovery-secret',
    }),
    error => error.message.includes('Unable to verify recovery details'),
  );
  assert.equal(storage.values.size, 0);
});

test('auth config only accepts same-server redirect urls', async () => {
  const storage = createStorage();
  const { fetchImpl } = createFetch([
    {
      match: url => url.endsWith('/accounts/auth-config/'),
      respond: () => response({
        body: {
          providers: [{ id: 'trakt', name: 'Trakt', loginUrl: '/accounts/trakt/login/' }],
          connectionsUrl: '/accounts/3rdparty/',
          deviceUrl: '/oauth/device',
        },
      }),
    },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });
  const config = await auth.fetchAuthConfig({ serverUrl: 'floppy.example' });
  assert.equal(config.providers[0].loginUrl, 'https://floppy.example/accounts/trakt/login/');
  assert.equal(config.connectionsUrl, 'https://floppy.example/accounts/3rdparty/');
  assert.equal(config.deviceUrl, 'https://floppy.example/oauth/device');
});

test('auth config errors do not display an HTML error page as field text', async () => {
  const storage = createStorage();
  const { fetchImpl } = createFetch([
    {
      match: url => url.endsWith('/accounts/auth-config/'),
      respond: () => response({ status: 404, body: '<!DOCTYPE html><html><title>Page not found</title></html>' }),
    },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });

  await assert.rejects(
    () => auth.fetchAuthConfig({ serverUrl: 'https://floppy.example' }),
    error => error.message === 'The server does not expose this endpoint.' && !error.message.includes('<html>'),
  );
});

test('auth config discovery requests pass through their cancellation signal', async () => {
  const storage = createStorage();
  const controller = new AbortController();
  const { fetchImpl, calls } = createFetch([
    {
      match: url => url.endsWith('/accounts/auth-config/'),
      respond: () => response({ body: { registrationEnabled: true } }),
    },
  ]);
  const auth = createAuthTransport({ storage, fetchImpl });

  await auth.fetchAuthConfig({ serverUrl: 'http://192.168.1.20:8000', signal: controller.signal });

  assert.equal(calls[0].options.signal, controller.signal);
});
