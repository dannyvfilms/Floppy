import assert from 'node:assert/strict';
import test from 'node:test';
import {
  AUTH_ERROR_CODES,
  AuthError,
  buildDeviceVerificationUrl,
  buildProviderLoginUrl,
  normalizeServerUrl,
  safeRedirectPath,
} from './authTransportCore.js';

test('safeRedirectPath keeps same-origin relative paths with query and hash', () => {
  assert.equal(safeRedirectPath('/library?tab=all#row-3'), '/library?tab=all#row-3');
  assert.equal(safeRedirectPath('  /settings  '), '/settings');
});

test('safeRedirectPath falls back on protocol-relative, backslash and control characters', () => {
  assert.equal(safeRedirectPath('//evil.example/x'), '/');
  assert.equal(safeRedirectPath('/\\evil'), '/');
  assert.equal(safeRedirectPath('/a\u0000b'), '/');
  assert.equal(safeRedirectPath('https://elsewhere.example/x'), '/');
});

test('safeRedirectPath rejects oversized and empty values', () => {
  assert.equal(safeRedirectPath(`/${'a'.repeat(2001)}`), '/');
  assert.equal(safeRedirectPath('', '/onboarding'), '/onboarding');
  assert.equal(safeRedirectPath(undefined), '/');
});

test('normalizeServerUrl adds the scheme and strips paths and trailing slashes', () => {
  assert.equal(normalizeServerUrl('myserver.example'), 'https://myserver.example');
  assert.equal(normalizeServerUrl('http://myserver.example/base/'), 'http://myserver.example/base');
  assert.equal(normalizeServerUrl('https://myserver.example//'), 'https://myserver.example');
});

test('normalizeServerUrl rejects empty, non-http and decorated addresses', () => {
  assert.throws(
    () => normalizeServerUrl(''),
    error => error instanceof AuthError && error.code === AUTH_ERROR_CODES.INVALID_SERVER,
  );
  assert.throws(() => normalizeServerUrl('ftp://myserver.example'), /http or https/);
  assert.throws(() => normalizeServerUrl('https://user:pass@myserver.example'), /credentials/);
  assert.throws(() => normalizeServerUrl('https://myserver.example/?a=1'), /query or fragment/);
  assert.throws(() => normalizeServerUrl('https://myserver.example/#row'), /query or fragment/);
});

test('buildProviderLoginUrl builds the login route and rejects bad provider ids', () => {
  assert.equal(
    buildProviderLoginUrl({ serverUrl: 'myserver.example', providerId: 'oidc' }),
    // redirectTo defaults to '/', so next=%2F is always present.
    'https://myserver.example/accounts/oidc/login/?process=login&next=%2F',
  );
  assert.equal(
    buildProviderLoginUrl({ serverUrl: 'myserver.example', providerId: 'oidc', redirectTo: '/library' }),
    'https://myserver.example/accounts/oidc/login/?process=login&next=%2Flibrary',
  );
  assert.throws(
    () => buildProviderLoginUrl({ serverUrl: 'myserver.example', providerId: 'bad provider' }),
    AuthError,
  );
  assert.throws(
    () => buildProviderLoginUrl({ serverUrl: 'myserver.example', providerId: '' }),
    AuthError,
  );
});

test('buildDeviceVerificationUrl appends the user code only when present', () => {
  assert.equal(
    buildDeviceVerificationUrl({ serverUrl: 'myserver.example' }),
    'https://myserver.example/oauth/device',
  );
  assert.equal(
    buildDeviceVerificationUrl({ serverUrl: 'myserver.example', userCode: ' ABCD-EFGH ' }),
    'https://myserver.example/oauth/device?user_code=ABCD-EFGH',
  );
});

test('AuthError defaults to the request_failed code and status 0', () => {
  const error = new AuthError('boom');
  assert.equal(error.name, 'AuthError');
  assert.equal(error.code, AUTH_ERROR_CODES.REQUEST_FAILED);
  assert.equal(error.status, 0);
});
