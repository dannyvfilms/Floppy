"""Exercise playback polling with a delayed browser response."""

import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class PlaybackPollingTests(SimpleTestCase):
    """Pin completion-driven polling and bounded recovery backoff."""

    def test_delayed_response_cannot_overlap_next_poll(self):
        """Wait for completion, then back off slow and failed polls."""
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        template = Path(settings.BASE_DIR) / "templates/app/components/_scrollable_row_js.html"
        code = template.read_text().split("<script>", 1)[1].split("</script>", 1)[0]
        harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const timers = new Map(), events = new Map();
let clock = 0, serial = 0, requests = 0;
const container = {id: 'active-playback-container', isConnected: true,
                   matches: () => false};
const context = {
  window: {}, document: {readyState: 'complete',
    getElementById: () => container, querySelectorAll: () => [],
    body: {addEventListener: (name, fn) => events.set(name, fn)}},
  loadVisibleReleaseYears: () => {}, performance: {now: () => clock},
  requestAnimationFrame: fn => fn(),
  setInterval: () => 1, clearInterval: () => {},
  setTimeout: (fn, delay) => {const id = ++serial; timers.set(id, {fn, delay}); return id;},
  clearTimeout: id => timers.delete(id),
  htmx: {trigger: (elt, name) => {
    assert.equal(name, 'playback-poll'); requests++;
    events.get('htmx:beforeRequest')({detail: {elt}});
  }},
};
vm.createContext(context);
vm.runInContext(process.argv[1], context);
assert.equal(timers.size, 1);
assert.equal([...timers.values()][0].delay, 10000);
function fire() {const [id, timer] = [...timers][0]; timers.delete(id); timer.fn();}
function complete(successful, elapsed) {
  clock += elapsed;
  events.get('htmx:afterRequest')({detail: {elt: container, successful}});
}
fire(); assert.equal(requests, 1); assert.equal(timers.size, 0);
clock += 24000;
context.scheduleActivePlaybackPoll(); context.scheduleActivePlaybackPoll();
assert.equal(requests, 1); assert.equal(timers.size, 0);
complete(true, 0); assert.equal([...timers.values()][0].delay, 20000);
context.scheduleActivePlaybackPoll(); assert.equal(timers.size, 1);
fire(); complete(false, 1); assert.equal([...timers.values()][0].delay, 30000);
fire(); complete(true, 1); assert.equal([...timers.values()][0].delay, 10000);
container.isConnected = false; fire(); assert.equal(requests, 3);
console.log('polling selfcheck passed');
"""
        result = subprocess.run(  # noqa: S603 -- installed Node, repository source, no user input
            [node, "-e", harness, code], capture_output=True, text=True,
            timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("polling selfcheck passed", result.stdout)
