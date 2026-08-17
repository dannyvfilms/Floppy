// Self-check for CacheUpdater network failure behavior. This project has no
// browser-JS test runner, so keep this as a plain assert script:
// `node src/static/js/cache-updater.selfcheck.mjs`.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const realSetTimeout = globalThis.setTimeout;
const realClearTimeout = globalThis.clearTimeout;
const realFetch = globalThis.fetch;
const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
const realConsole = globalThis.console;

let nextTimerId = 1;
let timers = new Map();
const listeners = new Map();

function resetTimers() {
    timers = new Map();
    nextTimerId = 1;
}

function timerDelays() {
    return [...timers.values()].map((timer) => timer.delay).sort((a, b) => a - b);
}

function response(status, body = {}, headers = {}) {
    const normalizedHeaders = Object.fromEntries(
        Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]),
    );
    return {
        ok: status >= 200 && status < 300,
        status,
        headers: {
            get(name) {
                return normalizedHeaders[name.toLowerCase()] ?? null;
            },
        },
        async json() {
            return body;
        },
    };
}

function resetEnvironment() {
    resetTimers();
    listeners.clear();
    window.location.pathname = '/statistics';
    navigator.onLine = true;
}

try {
    globalThis.window = globalThis;
    window.location = { pathname: '/statistics', reload() {} };
    window.addEventListener = (type, callback) => listeners.set(type, callback);
    window.removeEventListener = (type, callback) => {
        if (listeners.get(type) === callback) {
            listeners.delete(type);
        }
    };
    Object.defineProperty(globalThis, 'navigator', {
        configurable: true,
        value: { onLine: true },
    });
    globalThis.setTimeout = (callback, delay) => {
        const id = nextTimerId++;
        timers.set(id, { callback, delay });
        return id;
    };
    globalThis.clearTimeout = (id) => timers.delete(id);
    // Keep expected failure-path logging out of the self-check output.
    globalThis.console = {
        ...realConsole,
        log() {},
        warn() {},
        error() {},
    };

    const src = fs.readFileSync(path.join(dir, 'cache-updater.js'), 'utf8');
    new Function(src)();
    const CacheUpdater = window.CacheUpdater;

    // A permanent 404 must stop after one request. The old behavior retried at
    // 2.5-second intervals until the 180-second overall timeout.
    resetEnvironment();
    let fetchCount = 0;
    let completion = null;
    globalThis.fetch = async () => {
        fetchCount += 1;
        return response(404);
    };
    let updater = new CacheUpdater('statistics', {
        onRefreshComplete(success, reason) {
            completion = [success, reason];
        },
    });
    updater.isPolling = true;
    await updater.poll();
    assert.equal(fetchCount, 1);
    assert.equal(updater.isPolling, false);
    assert.deepEqual(timerDelays(), []);
    assert.deepEqual(completion, [false, 'http_404']);

    // Transient server failures retry with exponential backoff, not a fixed
    // request loop.
    resetEnvironment();
    globalThis.fetch = async () => response(503);
    updater = new CacheUpdater('statistics');
    updater.isPolling = true;
    await updater.poll();
    assert.deepEqual(timerDelays(), [2500]);
    assert.equal(updater.retryAttempt, 1);
    for (const id of [...timers.keys()]) {
        clearTimeout(id);
    }
    await updater.poll();
    assert.deepEqual(timerDelays(), [5000]);
    assert.equal(updater.retryAttempt, 2);
    updater.stop();

    // Retry-After takes precedence when the server asks for a longer pause.
    resetEnvironment();
    globalThis.fetch = async () => response(429, {}, { 'Retry-After': '10' });
    updater = new CacheUpdater('statistics');
    updater.isPolling = true;
    await updater.poll();
    assert.deepEqual(timerDelays(), [10000]);
    updater.stop();

    // When the browser is offline, do not send a request or schedule a timer.
    // The online event resumes the same updater later.
    resetEnvironment();
    navigator.onLine = false;
    fetchCount = 0;
    globalThis.fetch = async () => {
        fetchCount += 1;
        return response(200, {});
    };
    updater = new CacheUpdater('statistics');
    updater.isPolling = true;
    await updater.poll();
    assert.equal(fetchCount, 0);
    assert.notEqual(updater.offlineSince, null);
    assert.deepEqual(timerDelays(), []);
    navigator.onLine = true;
    updater.stop();

    // Stopping an updater aborts its in-flight request and must not create a
    // retry after the abort settles.
    resetEnvironment();
    let wasAborted = false;
    globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => {
            wasAborted = true;
            const error = new Error('aborted');
            error.name = 'AbortError';
            reject(error);
        }, { once: true });
    });
    updater = new CacheUpdater('statistics');
    updater.isPolling = true;
    const stoppedRequest = updater.poll();
    assert.notEqual(updater.abortController, null);
    updater.stop();
    await stoppedRequest;
    assert.equal(wasAborted, true);
    assert.equal(updater.isPolling, false);
    assert.deepEqual(timerDelays(), []);

    // A single hung request has its own deadline. Once aborted by that
    // deadline, it enters the same bounded transient-failure backoff.
    resetEnvironment();
    globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => {
            const error = new Error('aborted');
            error.name = 'AbortError';
            reject(error);
        }, { once: true });
    });
    updater = new CacheUpdater('statistics', { requestTimeout: 1000 });
    updater.isPolling = true;
    const timedRequest = updater.poll();
    const timeoutEntry = [...timers.entries()].find(([, timer]) => timer.delay === 1000);
    assert.ok(timeoutEntry, 'request timeout timer should exist');
    const [timeoutId, timeoutTimer] = timeoutEntry;
    timers.delete(timeoutId);
    timeoutTimer.callback();
    await timedRequest;
    assert.deepEqual(timerDelays(), [2500]);
    assert.equal(updater.retryAttempt, 1);
    updater.stop();

    // A healthy refresh keeps the existing 2.5-second cadence and clears any
    // previous failure backoff state.
    resetEnvironment();
    globalThis.fetch = async () => response(200, {
        exists: true,
        is_stale: true,
        is_refreshing: true,
        refresh_scheduled: false,
        metadata_refreshing: false,
        any_range_refreshing: false,
        built_at: null,
    });
    updater = new CacheUpdater('statistics');
    updater.isPolling = true;
    updater.retryAttempt = 3;
    await updater.poll();
    assert.deepEqual(timerDelays(), [2500]);
    assert.equal(updater.retryAttempt, 0);
    updater.stop();

    realConsole.log('cache-updater self-check passed');
} finally {
    globalThis.setTimeout = realSetTimeout;
    globalThis.clearTimeout = realClearTimeout;
    globalThis.fetch = realFetch;
    globalThis.console = realConsole;
    if (navigatorDescriptor) {
        Object.defineProperty(globalThis, 'navigator', navigatorDescriptor);
    } else {
        delete globalThis.navigator;
    }
}
