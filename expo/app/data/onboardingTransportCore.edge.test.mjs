import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createLocalOnboardingActions,
  createRemoteOnboardingActions,
  mediaTypeSelection,
  onboardingOffer,
  sourceSelection,
} from './onboardingTransportCore.js';

test('remote onboarding sends the index query only past the first step', async () => {
  const calls = [];
  const transport = createRemoteOnboardingActions(async (path, options) => {
    calls.push({ path, options });
    return {};
  });
  await transport.load();
  await transport.load({ index: 2 });
  await transport.act('next', { value: 1 });
  await transport.act('skip');
  assert.deepEqual(calls[0], { path: '/api/v1/user/onboarding/', options: { query: undefined } });
  assert.deepEqual(calls[1].options, { query: { index: 2 } });
  assert.deepEqual(calls[2].options, { method: 'POST', body: { action: 'next', value: 1 } });
  assert.deepEqual(calls[3].options.body, { action: 'skip' });
});

test('the local onboarding transport answers with the sign-in reason', async () => {
  const transport = createLocalOnboardingActions('Sign in to finish setting up.');
  assert.equal(transport.mode, 'local');
  const local = { local: true, reason: 'Sign in to finish setting up.' };
  assert.deepEqual(await transport.load(), local);
  assert.deepEqual(await transport.act('next'), local);
});

test('onboardingOffer only opens by itself right after sign-up', () => {
  assert.deepEqual(onboardingOffer(null), { banner: false, open: false });
  assert.deepEqual(onboardingOffer({ local: true }, { justSignedUp: true }), { banner: false, open: false });
  assert.deepEqual(onboardingOffer({ demo: true }), { banner: false, open: false });
  assert.deepEqual(onboardingOffer({ status: 'completed' }, { justSignedUp: true }), { banner: false, open: false });
  assert.deepEqual(onboardingOffer({ status: 'in_progress' }), { banner: true, open: false });
  assert.deepEqual(onboardingOffer({ status: 'in_progress' }, { justSignedUp: true }), { banner: true, open: true });
  assert.deepEqual(onboardingOffer({ status: 'banana' }), { banner: false, open: false });
  assert.deepEqual(onboardingOffer({}, { justSignedUp: true }), { banner: false, open: true });
});

test('media type and source selections toggle values', () => {
  assert.deepEqual(mediaTypeSelection(['movie'], 'movie'), []);
  assert.deepEqual(mediaTypeSelection(['movie'], 'tv'), ['movie', 'tv']);
  assert.deepEqual(sourceSelection(['tmdb'], 'tmdb'), []);
  assert.deepEqual(sourceSelection([], 'tmdb'), ['tmdb']);
  assert.deepEqual(mediaTypeSelection([], 'movie'), ['movie']);
});
