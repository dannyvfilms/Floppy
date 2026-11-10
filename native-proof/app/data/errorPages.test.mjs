import assert from 'node:assert/strict';
import test from 'node:test';
import { ERROR_PAGES, errorPageFor, errorPageWithMessage } from './errorPages.js';

test('transport failures map to the matching server error page', () => {
  assert.equal(errorPageFor({ code: 'server_unreachable' }), ERROR_PAGES.offline);
  assert.equal(errorPageFor(new Error('offline')), ERROR_PAGES.offline);
  assert.equal(errorPageFor({ code: 'forbidden', status: 403 }), ERROR_PAGES[403]);
  assert.equal(errorPageFor({ code: 'not_found', status: 404 }), ERROR_PAGES[404]);
  assert.equal(errorPageFor({ code: 'server', status: 502 }), ERROR_PAGES[500]);
  assert.equal(errorPageFor({ code: 'request_failed', status: 400 }), ERROR_PAGES[400]);
});

test('a plain server message replaces generic copy but not the offline state', () => {
  assert.equal(errorPageWithMessage({ status: 404, message: 'That list was deleted.' }).message, 'That list was deleted.');
  assert.equal(errorPageWithMessage({ code: 'server_unreachable', message: 'x' }).message, ERROR_PAGES.offline.message);
});

test('no error page points at an example host', () => {
  assert.equal(JSON.stringify(ERROR_PAGES).includes('example.com'), false);
});
