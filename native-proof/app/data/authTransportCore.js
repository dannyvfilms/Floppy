const STORAGE_KEY = 'floppy.auth.session.v1';
const SESSION_VERSION = 1;
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export const AUTH_ERROR_CODES = Object.freeze({
  INVALID_SERVER: 'invalid_server',
  INVALID_CREDENTIALS: 'invalid_credentials',
  SIGNED_OUT: 'signed_out',
  EXPIRED: 'expired',
  REVOKED: 'revoked',
  FORBIDDEN: 'forbidden',
  CSRF: 'csrf',
  NOT_FOUND: 'not_found',
  RATE_LIMITED: 'rate_limited',
  SERVER: 'server',
  SERVER_UNREACHABLE: 'server_unreachable',
  UNSUPPORTED: 'unsupported',
  REQUEST_FAILED: 'request_failed',
});

export class AuthError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = 'AuthError';
    this.code = options.code || AUTH_ERROR_CODES.REQUEST_FAILED;
    this.status = options.status || 0;
  }
}

function fail(code, message, options = {}) {
  return new AuthError(message, { ...options, code });
}

function normalizeToken(value) {
  return String(value || '').trim().replace(/^Bearer\s+/i, '');
}

export function normalizeServerUrl(input) {
  const value = String(input || '').trim();
  if (!value) {
    throw fail(AUTH_ERROR_CODES.INVALID_SERVER, 'Enter the address of your Floppy server.');
  }
  let url;
  try {
    url = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : `https://${value}`);
  } catch {
    throw fail(AUTH_ERROR_CODES.INVALID_SERVER, 'Enter a valid Floppy server address.');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw fail(AUTH_ERROR_CODES.INVALID_SERVER, 'The Floppy server address must use http or https.');
  }
  if (url.username || url.password) {
    throw fail(AUTH_ERROR_CODES.INVALID_SERVER, 'Do not include credentials in the server address.');
  }
  if (url.search || url.hash) {
    throw fail(AUTH_ERROR_CODES.INVALID_SERVER, 'Enter the server address without a query or fragment.');
  }
  const path = url.pathname.replace(/\/+$/, '');
  return `${url.origin}${path === '/' ? '' : path}`;
}

function queryString(query = {}) {
  const parts = Object.entries(query)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

function requestUrl(baseUrl, path, query) {
  const value = String(path || '');
  if (!value.startsWith('/') || value.startsWith('//')) {
    throw fail(AUTH_ERROR_CODES.REQUEST_FAILED, 'The request path must be relative to the Floppy server.');
  }
  return `${baseUrl}${value}${queryString(query)}`;
}

function headerValue(headers, name) {
  if (!headers) return '';
  if (typeof headers.get === 'function') {
    return headers.get(name) || '';
  }
  const key = Object.keys(headers).find(entry => entry.toLowerCase() === name.toLowerCase());
  return key ? headers[key] : '';
}

function setCookies(response) {
  if (!response || !response.headers) return [];
  if (typeof response.headers.getSetCookie === 'function') {
    return response.headers.getSetCookie();
  }
  const raw = headerValue(response.headers, 'set-cookie');
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  return String(raw).split(/,(?=\s*[^;,=\s]+=)/);
}

function cookieName(raw) {
  const pair = String(raw || '').split(';')[0];
  const index = pair.indexOf('=');
  if (index <= 0) return '';
  return pair.slice(0, index).trim();
}

function cookieValue(raw) {
  const pair = String(raw || '').split(';')[0];
  const index = pair.indexOf('=');
  return index >= 0 ? pair.slice(index + 1).trim() : '';
}

function mergeCookies(cookies, response) {
  const next = { ...cookies };
  setCookies(response).forEach(raw => {
    const name = cookieName(raw);
    if (!name) return;
    const value = cookieValue(raw);
    if (!value || /max-age=0/i.test(String(raw))) {
      delete next[name];
      return;
    }
    next[name] = value;
  });
  return next;
}

function cookieHeader(cookies) {
  return Object.entries(cookies)
    .filter(([name]) => name === 'sessionid' || name === 'csrftoken')
    .map(([name, value]) => `${name}=${value}`)
    .join('; ');
}

function extractDetail(data) {
  if (!data) return '';
  if (typeof data === 'string') return data.trim().slice(0, 300);
  const value = data.detail || data.error || data.message;
  return typeof value === 'string' ? value.trim().slice(0, 300) : '';
}

function redact(message, session) {
  let text = String(message || '');
  const secrets = [session && session.token, session && session.csrfToken];
  if (session && session.cookies) {
    Object.values(session.cookies).forEach(value => secrets.push(value));
  }
  secrets.filter(Boolean).forEach(secret => {
    text = text.split(String(secret)).join('[redacted]');
  });
  return text;
}

function isCsrfFailure(data) {
  const text = `${extractDetail(data)} ${typeof data === 'string' ? data : ''}`;
  return /csrf/i.test(text);
}

async function readBody(response) {
  try {
    const text = typeof response.text === 'function' ? await response.text() : '';
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  } catch {
    return null;
  }
}

function classifyFailure(response, data, session) {
  const detail = extractDetail(data);
  if (response.status === 401) {
    const expired = /expired/i.test(detail);
    if (session && session.authType === 'token' && !expired) {
      return fail(AUTH_ERROR_CODES.REVOKED, 'The access token was revoked or is no longer valid.', { status: response.status });
    }
    return fail(AUTH_ERROR_CODES.EXPIRED, 'The saved session has expired. Sign in again.', { status: response.status });
  }
  if (response.status === 403) {
    if (isCsrfFailure(data)) {
      return fail(AUTH_ERROR_CODES.CSRF, 'The security token expired. Try the request again.', { status: response.status });
    }
    return fail(AUTH_ERROR_CODES.FORBIDDEN, detail || 'The server denied this request.', { status: response.status });
  }
  if (response.status === 404) {
    return fail(AUTH_ERROR_CODES.NOT_FOUND, detail || 'The server does not expose this endpoint.', { status: response.status });
  }
  if (response.status === 429) {
    return fail(AUTH_ERROR_CODES.RATE_LIMITED, 'Too many requests. Wait a moment and try again.', { status: response.status });
  }
  if (response.status >= 500) {
    return fail(AUTH_ERROR_CODES.SERVER, 'The Floppy server returned an error. Try again later.', { status: response.status });
  }
  return fail(AUTH_ERROR_CODES.REQUEST_FAILED, detail || `The server rejected the request (${response.status}).`, { status: response.status });
}

function publicSession(session) {
  if (!session) return null;
  return {
    serverUrl: session.serverUrl,
    authType: session.authType,
    user: session.user || null,
    lastVerifiedAt: session.lastVerifiedAt || null,
  };
}

function publicState(state) {
  return {
    status: state.status,
    serverUrl: state.serverUrl,
    authType: state.authType,
    user: state.user,
    hasCredential: state.status === 'authenticated',
    error: state.error,
  };
}

function sessionFacade(session, api) {
  if (!session) return null;
  return {
    serverUrl: session.serverUrl,
    authType: session.authType,
    user: session.user || null,
    request: (path, options) => api.request(path, options),
    getState: () => publicState(api.state),
    invalidate: () => api.invalidate(AUTH_ERROR_CODES.SIGNED_OUT),
  };
}

export function createAuthTransport({ storage, fetchImpl, onSessionChange, now = () => Date.now() } = {}) {
  if (!storage || typeof storage.getItem !== 'function') {
    throw new TypeError('createAuthTransport requires a storage adapter.');
  }
  const fetcher = fetchImpl || ((...args) => fetch(...args));
  const state = {
    status: 'signed_out',
    serverUrl: '',
    authType: '',
    user: null,
    error: null,
  };
  let session = null;

  function publish() {
    if (onSessionChange) {
      onSessionChange(sessionFacade(session, api));
    }
  }

  function setState(next) {
    Object.assign(state, next);
  }

  async function persist(next) {
    await storage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  async function removeStored() {
    await storage.removeItem(STORAGE_KEY);
  }

  async function invalidate(code) {
    await removeStored().catch(() => {});
    setState({
      status: code === AUTH_ERROR_CODES.REVOKED ? 'revoked' : code === AUTH_ERROR_CODES.EXPIRED ? 'expired' : 'signed_out',
      authType: '',
      user: state.user,
      error: code,
    });
    session = null;
    publish();
    return publicState(state);
  }

  async function perform(url, options) {
    try {
      return await fetcher(url, options);
    } catch {
      throw fail(AUTH_ERROR_CODES.SERVER_UNREACHABLE, 'Could not reach the Floppy server. Check the address and connection.');
    }
  }

  function authHeaders(target, method, current) {
    const headers = { Accept: 'application/json' };
    if (current.authType === 'token') {
      headers.Authorization = `Bearer ${current.token}`;
    } else if (current.cookieText) {
      headers.Cookie = current.cookieText;
      if (current.csrfToken) headers['X-CSRFToken'] = current.csrfToken;
      if (!SAFE_METHODS.has(method)) {
        headers.Origin = target;
        headers.Referer = `${target}/`;
      }
    }
    return headers;
  }

  async function refreshCsrf(current) {
    const target = current.serverUrl;
    const response = await perform(`${target}/login/`, {
      method: 'GET',
      headers: { Accept: 'text/html' },
    });
    if (!response.ok) {
      throw fail(AUTH_ERROR_CODES.CSRF, 'Could not refresh the security token. Sign in again.', { status: response.status });
    }
    current.cookies = mergeCookies(current.cookies || {}, response);
    current.csrfToken = current.cookies.csrftoken || '';
    current.cookieText = cookieHeader(current.cookies);
    if (!current.csrfToken) {
      throw fail(AUTH_ERROR_CODES.CSRF, 'The server did not provide a security token. Sign in again.');
    }
    if (current === session) await persist(session).catch(() => {});
    return current;
  }

  async function send(current, path, options = {}) {
    const method = String(options.method || 'GET').toUpperCase();
    const target = current.serverUrl;
    const headers = {
      ...authHeaders(target, method, current),
      ...(options.headers || {}),
    };
    let body;
    if (options.body !== undefined || options.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.body !== undefined ? options.body : options.json);
    } else if (options.form !== undefined) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
      const params = new URLSearchParams();
      Object.entries(options.form).forEach(([key, value]) => {
        if (Array.isArray(value)) {
          value.forEach(item => params.append(key, String(item)));
        } else if (value !== undefined && value !== null) {
          params.append(key, String(value));
        }
      });
      body = params.toString();
    }
    const response = await perform(requestUrl(target, path, options.query), {
      method,
      headers,
      body,
      credentials: current.authType === 'token' ? 'omit' : 'include',
    });
    const data = await readBody(response);
    if (response.status === 403 && current.authType === 'session' && isCsrfFailure(data) && !options.csrfRetried) {
      await refreshCsrf(current);
      return send(current, path, { ...options, csrfRetried: true });
    }
    if (!response.ok) {
      const error = classifyFailure(response, data, current);
      error.message = redact(error.message, current);
      if (current === session && (error.code === AUTH_ERROR_CODES.EXPIRED || error.code === AUTH_ERROR_CODES.REVOKED)) {
        await invalidate(error.code);
      }
      throw error;
    }
    return data;
  }

  async function verifyCredential(current, path = '/api/v1/user/sidebar/') {
    return send(current, path);
  }

  async function signInWithToken({ serverUrl, token, user } = {}) {
    const baseUrl = normalizeServerUrl(serverUrl);
    const value = normalizeToken(token);
    if (!value) {
      throw fail(AUTH_ERROR_CODES.INVALID_CREDENTIALS, 'Enter an access token or sign in with a username and password.');
    }
    setState({ status: 'authenticating', serverUrl: baseUrl, authType: 'token', user: user || null, error: null });
    publish();
    const candidate = {
      version: SESSION_VERSION,
      serverUrl: baseUrl,
      authType: 'token',
      token: value,
      user: user || null,
      createdAt: now(),
      lastVerifiedAt: null,
    };
    session = candidate;
    try {
      await verifyCredential(candidate);
    } catch (error) {
      session = null;
      setState({ status: 'signed_out', authType: '', user: null, error: error.code });
      publish();
      throw error;
    }
    candidate.lastVerifiedAt = now();
    await persist(candidate);
    setState({ status: 'authenticated', authType: 'token', user: candidate.user, error: null });
    publish();
    return publicState(state);
  }

  async function signIn({ serverUrl, username, password, remember = true } = {}) {
    const baseUrl = normalizeServerUrl(serverUrl);
    const login = String(username || '').trim();
    const secret = String(password || '');
    if (!login || !secret) {
      throw fail(AUTH_ERROR_CODES.INVALID_CREDENTIALS, 'Enter your username and password.');
    }
    setState({ status: 'authenticating', serverUrl: baseUrl, authType: 'session', user: { username: login }, error: null });
    publish();

    const loginPage = await perform(`${baseUrl}/login/`, {
      method: 'GET',
      headers: { Accept: 'text/html' },
    });
    if (!loginPage.ok) {
      setState({ status: 'signed_out', error: AUTH_ERROR_CODES.INVALID_SERVER });
      publish();
      throw fail(AUTH_ERROR_CODES.INVALID_SERVER, 'The server login page could not be loaded.', { status: loginPage.status });
    }
    let cookies = mergeCookies({}, loginPage);
    let csrfToken = cookies.csrftoken || '';
    if (!csrfToken) {
      setState({ status: 'signed_out', error: AUTH_ERROR_CODES.CSRF });
      publish();
      throw fail(AUTH_ERROR_CODES.CSRF, 'The server did not provide a login security token.');
    }

    async function postLogin() {
      const form = new URLSearchParams({
        login,
        password: secret,
        csrfmiddlewaretoken: csrfToken,
      });
      if (remember) form.set('remember', 'on');
      return perform(`${baseUrl}/accounts/login/`, {
        method: 'POST',
        headers: {
          Accept: 'text/html, application/json',
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrfToken,
          Cookie: cookieHeader(cookies),
          Origin: baseUrl,
          Referer: `${baseUrl}/login/`,
        },
        body: form.toString(),
        credentials: 'omit',
      });
    }

    let response = await postLogin();
    if (response.status === 403) {
      cookies = mergeCookies(cookies, response);
      csrfToken = cookies.csrftoken || '';
      if (csrfToken) response = await postLogin();
    }
    cookies = mergeCookies(cookies, response);
    const candidate = {
      version: SESSION_VERSION,
      serverUrl: baseUrl,
      authType: 'session',
      cookies,
      csrfToken: cookies.csrftoken || csrfToken,
      cookieText: cookieHeader(cookies),
      user: { username: login },
      createdAt: now(),
      lastVerifiedAt: null,
    };
    session = candidate;
    try {
      await verifyCredential(candidate);
    } catch (error) {
      session = null;
      setState({ status: 'signed_out', authType: '', user: null, error: error.code });
      publish();
      if (error.code === AUTH_ERROR_CODES.EXPIRED) {
        throw fail(AUTH_ERROR_CODES.INVALID_CREDENTIALS, 'Sign-in failed. Check your username and password.');
      }
      throw error;
    }
    candidate.lastVerifiedAt = now();
    await persist(candidate);
    setState({ status: 'authenticated', authType: 'session', user: candidate.user, error: null });
    publish();
    return publicState(state);
  }

  async function restore() {
    let stored = null;
    try {
      stored = await storage.getItem(STORAGE_KEY);
    } catch {
      stored = null;
    }
    if (!stored) {
      setState({ status: 'signed_out', authType: '', user: null, error: null });
      session = null;
      publish();
      return publicState(state);
    }
    let parsed;
    try {
      parsed = JSON.parse(stored);
    } catch {
      await removeStored().catch(() => {});
      setState({ status: 'signed_out', authType: '', user: null, error: null });
      session = null;
      publish();
      return publicState(state);
    }
    if (!parsed || parsed.version !== SESSION_VERSION || !parsed.serverUrl || !['token', 'session'].includes(parsed.authType)) {
      await removeStored().catch(() => {});
      setState({ status: 'signed_out', authType: '', user: null, error: null });
      session = null;
      publish();
      return publicState(state);
    }
    session = parsed;
    setState({
      status: 'authenticated',
      serverUrl: parsed.serverUrl,
      authType: parsed.authType,
      user: parsed.user || null,
      error: null,
    });
    publish();
    return publicState(state);
  }

  async function signOut() {
    if (session && session.authType === 'session') {
      try {
        await send(session, '/accounts/logout/', { method: 'POST', body: {} });
      } catch {
        // Local sign-out still removes the saved credential.
      }
    }
    await removeStored().catch(() => {});
    session = null;
    setState({ status: 'signed_out', authType: '', user: null, error: null });
    publish();
    return publicState(state);
  }

  async function testConnection({ serverUrl, token } = {}) {
    const baseUrl = normalizeServerUrl(serverUrl);
    const ping = await perform(`${baseUrl}/ping/`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    });
    const pingData = await readBody(ping);
    if (!ping.ok || (pingData && typeof pingData === 'object' && pingData.status && pingData.status !== 'ok')) {
      throw fail(AUTH_ERROR_CODES.SERVER_UNREACHABLE, 'The address did not answer like a Floppy server.', { status: ping.status });
    }
    const value = normalizeToken(token);
    if (!value) {
      return { reachable: true, authenticated: false, serverUrl: baseUrl, user: null };
    }
    const candidate = { serverUrl: baseUrl, authType: 'token', token: value };
    const sidebar = await send(candidate, '/api/v1/user/sidebar/');
    return {
      reachable: true,
      authenticated: true,
      serverUrl: baseUrl,
      user: null,
      sidebar: sidebar || null,
    };
  }

  async function request(path, options = {}) {
    if (!session) {
      throw fail(AUTH_ERROR_CODES.SIGNED_OUT, 'Sign in to your Floppy server first.');
    }
    return send(session, path, options);
  }

  const api = {
    request,
    state,
    invalidate,
  };

  return {
    restore,
    signIn,
    signInWithToken,
    signOut,
    testConnection,
    request,
    getState: () => publicState(state),
    getSession: () => sessionFacade(session, api),
    invalidate,
  };
}
