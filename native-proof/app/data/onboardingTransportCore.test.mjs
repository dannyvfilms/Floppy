import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createLocalOnboardingActions,
  createRemoteOnboardingActions,
  mediaTypeSelection,
  onboardingOffer,
  sourceSelection,
} from './onboardingTransportCore.js';

test('loads the step and posts one action per request', async () => {
  const calls = [];
  const actions = createRemoteOnboardingActions(async (path, options) => { calls.push({ path, options }); return { step: 'media_types' }; });
  await actions.load();
  await actions.load({ index: 2 });
  await actions.act('media_types', { mediaTypes: ['movie'] });
  assert.equal(calls[0].path, '/api/v1/user/onboarding/');
  assert.equal(calls[0].options.query, undefined);
  assert.deepEqual(calls[1].options.query, { index: 2 });
  assert.equal(calls[2].options.method, 'POST');
  assert.deepEqual(calls[2].options.body, { action: 'media_types', mediaTypes: ['movie'] });
});

test('offers setup only while unfinished and opens it only after sign-up', () => {
  assert.deepEqual(onboardingOffer({ status: 'not_started' }), { banner: false, open: false });
  assert.deepEqual(onboardingOffer({ status: 'not_started' }, { justSignedUp: true }), { banner: false, open: true });
  assert.deepEqual(onboardingOffer({ status: 'in_progress' }), { banner: true, open: false });
  assert.deepEqual(onboardingOffer({ status: 'completed' }, { justSignedUp: true }), { banner: false, open: false });
  assert.deepEqual(onboardingOffer({ status: 'in_progress', demo: true }), { banner: false, open: false });
  assert.deepEqual(onboardingOffer(null), { banner: false, open: false });
});

test('selection helpers toggle without mutating', () => {
  const list = ['movie'];
  assert.deepEqual(mediaTypeSelection(list, 'tv'), ['movie', 'tv']);
  assert.deepEqual(mediaTypeSelection(list, 'movie'), []);
  assert.deepEqual(sourceSelection(['plex'], 'trakt'), ['plex', 'trakt']);
  assert.deepEqual(list, ['movie']);
});

test('a missing session returns a local reason instead of fake data', async () => {
  const local = createLocalOnboardingActions('Sign in first.');
  assert.equal(local.mode, 'local');
  assert.equal((await local.load()).reason, 'Sign in first.');
});
