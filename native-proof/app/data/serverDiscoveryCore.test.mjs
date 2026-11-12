import assert from 'node:assert/strict';
import test from 'node:test';
import { collectFloppyServers, verifyDiscoveredServers } from './serverDiscoveryCore.js';

test('only Floppy-marked HTTP services become discovery candidates', () => {
  const servers = collectFloppyServers([
    { name: 'Router', ipv4: ['192.168.1.1'], port: 80, txt: { path: '/' } },
    { name: 'Floppy', ipv4: ['192.168.1.20'], port: 8000, txt: { floppy: '1' } },
    { name: 'Invalid', ipv4: ['999.1.1.1'], port: 8000, txt: { floppy: '1' } },
    { name: 'Broken', ipv4: ['192.168.1.21'], port: 70000, txt: { floppy: '1' } },
  ]);

  assert.deepEqual(servers, [{
    name: 'Floppy',
    address: '192.168.1.20',
    port: 8000,
    serverUrl: 'http://192.168.1.20:8000',
  }]);
});

test('candidate verification checks the public auth config endpoint and drops failed services', async () => {
  const calls = [];
  const verified = await verifyDiscoveredServers([
    { name: 'Floppy', serverUrl: 'http://192.168.1.20:8000' },
    { name: 'Fake Floppy', serverUrl: 'http://192.168.1.21:80' },
  ], async options => {
    calls.push(options);
    if (options.serverUrl.endsWith('.21:80')) throw new Error('not a Floppy server');
    return { firstRun: false };
  });

  assert.equal(calls.length, 2);
  assert.equal(calls[0].signal instanceof AbortSignal, true);
  assert.deepEqual(verified.map(server => server.serverUrl), ['http://192.168.1.20:8000']);
});

test('candidate verification caps the number of public endpoint checks', async () => {
  const candidates = Array.from({ length: 10 }, (_, index) => ({
    name: `Floppy ${index}`,
    serverUrl: `http://192.168.1.${index + 1}:8000`,
  }));
  let checks = 0;
  await verifyDiscoveredServers(candidates, async () => {
    checks += 1;
    return {};
  }, { limit: 3 });
  assert.equal(checks, 3);
});
