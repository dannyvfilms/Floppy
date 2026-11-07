import assert from 'node:assert/strict';
import test from 'node:test';
import { AUTH_ERROR_CODES } from './authTransportCore.js';
import { createAccountTransport } from './authAccountCore.js';

function authFixture(handler) {
  const calls = [];
  let invalidated = null;
  return {
    calls,
    get invalidated() { return invalidated; },
    auth: {
      request: async (path, options = {}) => {
        calls.push({ path, options });
        return handler ? handler(path, options) : { ok: true };
      },
      invalidate: async code => { invalidated = code; return { status: 'signed_out', error: code }; },
    },
  };
}

test('account reads and writes use the native JSON contract', async () => {
  const fixture = authFixture(() => ({ ok: true, user: { username: 'nova' } }));
  const account = createAccountTransport({ auth: fixture.auth });
  assert.equal(account.mode, 'server');

  await account.load();
  assert.equal(fixture.calls[0].path, '/settings/account/');
  assert.equal(fixture.calls[0].options.method, 'GET');
  assert.equal(fixture.calls[0].options.headers['X-Floppy-Client'], 'native');
  assert.equal(fixture.calls[0].options.headers.Accept, 'application/json');

  await account.updateProfile({ username: ' nova ' });
  assert.deepEqual(fixture.calls[1].options.form, { username: 'nova' });

  await account.changePassword({ oldPassword: 'old', newPassword1: 'new', newPassword2: 'new' });
  assert.deepEqual(fixture.calls[2].options.form, {
    old_password: 'old',
    new_password1: 'new',
    new_password2: 'new',
  });

  await account.enableAuthenticator({ currentPassword: 'old', code: ' 123456 ' });
  assert.equal(fixture.calls[3].options.form.action, 'enable_authenticator');
  assert.equal(fixture.calls[3].options.form.current_password, 'old');
  assert.equal(fixture.calls[3].options.form.code, '123456');

  await account.startAuthenticatorSetup({ currentPassword: 'old' });
  assert.equal(fixture.calls[4].options.form.action, 'start_authenticator_setup');

  await account.disableAuthenticator({ currentPassword: 'old' });
  assert.equal(fixture.calls[5].options.form.action, 'disable_authenticator');

  await account.regenerateRecoveryCodes({ currentPassword: 'old' });
  assert.equal(fixture.calls[6].options.form.action, 'regenerate_recovery_codes');
});

test('deleting an account sends the confirmation and invalidates the session', async () => {
  const fixture = authFixture(() => ({ ok: true, deleted: true }));
  const account = createAccountTransport({ auth: fixture.auth });
  await account.deleteAccount({ currentPassword: 'old', confirmDelete: true });
  assert.deepEqual(fixture.calls[0].options.form, {
    action: 'delete_account',
    current_password: 'old',
    confirm_username: '',
    confirm_delete: 'on',
  });
  assert.equal(fixture.invalidated, AUTH_ERROR_CODES.SIGNED_OUT);
});

test('account transport refuses to run without a session', async () => {
  const account = createAccountTransport();
  assert.equal(account.mode, 'local');
  await assert.rejects(() => account.load(), error => error.code === AUTH_ERROR_CODES.SIGNED_OUT);
});
