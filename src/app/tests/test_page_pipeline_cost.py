"""Fixed per-page costs: what every full page load downloads and blocks on."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PagePipelineCostTests(TestCase):
    """Every page's head must stay cheap to load and cache."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="pipeline")

    def setUp(self):
        self.client.force_login(self.user)

    def test_translation_catalog_is_versioned_and_browser_cached(self):
        page = self.client.get(reverse("home")).content.decode()
        match = re.search(r'<script[^>]*\ssrc="(/jsi18n/\?v=[^"]+)"', page)

        self.assertIsNotNone(match, "the catalog URL must carry a version")
        catalog_url = match.group(1).replace("&amp;", "&")
        self.assertIn("&l=", catalog_url)

        response = self.client.get(catalog_url)

        self.assertEqual(response.status_code, 200)
        cache_control = response["Cache-Control"]
        self.assertIn("immutable", cache_control)
        self.assertIn("max-age=31536000", cache_control)

    def test_versioned_catalog_is_built_in_the_language_it_names(self):
        # The browser asks for English; the URL names German, and a shared
        # cache stores the response under that URL.
        response = self.client.get(
            reverse("javascript-catalog") + "?v=1&l=de", HTTP_ACCEPT_LANGUAGE="en"
        )

        self.assertContains(response, "Heute")
        self.assertIn("immutable", response["Cache-Control"])

    def test_unsupported_catalog_language_is_not_long_cached(self):
        response = self.client.get(reverse("javascript-catalog") + "?v=1&l=xx")

        self.assertNotIn("immutable", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_barcode_library_is_not_loaded_on_every_page(self):
        page = self.client.get(reverse("home")).content.decode()

        self.assertNotIn('<script src="/static/js/libraries/zxing', page)
        self.assertIn("data-zxing-src=", page)

    def test_boosted_page_does_not_redirect_and_reuses_warm_artwork(self):
        """A full response must not match its own login detector and load twice."""
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        page = self.client.get(reverse("home")).content.decode()
        source = next(
            script
            for script in re.findall(r"<script>(.*?)</script>", page, re.DOTALL)
            if "function initHtmxCacheBusting()" in script
        )
        source = (
            Path(settings.BASE_DIR, "static/js/artwork-loading.js").read_text() + source
        )
        check = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { source, page } = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const listeners = new Map();
function listen(name, fn) {
  const previous = listeners.get(name);
  listeners.set(name, previous ? event => { previous(event); fn(event); } : fn);
}
const redirects = [];
let entrance = false;
let images = [];
let savedArtwork = JSON.stringify(['http://localhost/remembered.jpg']);
const context = {
  URL,
  location: { href: 'http://localhost/lists' },
  window: {
    htmx: {}, location: { assign: url => redirects.push(url) },
    addEventListener: listen,
  },
  sessionStorage: {
    getItem: () => savedArtwork,
    setItem: (key, value) => { savedArtwork = value; },
  },
  htmx: { config: {} },
  document: {
    readyState: 'complete',
    addEventListener: listen,
    body: { addEventListener: listen },
  },
  DOMParser: class {
    parseFromString() {
      return {
        querySelector: () => entrance,
        querySelectorAll: () => images,
        documentElement: { outerHTML: 'warmed response' },
      };
    }
  },
};
vm.runInNewContext(source, context);
function swap() {
  const event = { detail: {
    xhr: { responseText: page, responseURL: 'http://localhost/lists' },
    serverResponse: page,
    shouldSwap: true,
  } };
  listeners.get('htmx:beforeSwap')(event);
  return event.detail;
}
// The response includes the detector script itself, but has no entrance meta.
assert.equal(swap().shouldSwap, true);
assert.deepEqual(redirects, []);
const remembered = {
  dataset: {},
  loading: 'lazy', getAttribute: () => '/remembered.jpg',
};
images = [remembered];
swap();
assert.equal(remembered.loading, 'eager'); // survives a full document navigation
assert.equal(remembered.dataset.artworkReady, 'true'); // skips entrance animations
const image = {
  dataset: {},
  loading: 'lazy', decoding: 'auto',
  getAttribute: () => '/poster.jpg',
};
images = [...Array.from({ length: 8 }, (_, index) => ({
  loading: 'lazy', decoding: 'auto', dataset: {},
  getAttribute: () => `/cold-${index}.jpg`,
})), image];
swap();
assert.ok(images.slice(0, 8).every(img => img.loading === 'eager'));
assert.ok(images.slice(0, 8).every(img => !img.dataset.artworkReady));
assert.equal(image.loading, 'lazy'); // unseen artwork beyond the first eight waits
listeners.get('load')({ target: {
  matches: () => true, naturalWidth: 100, src: 'http://localhost/poster.jpg',
} });
assert.equal(swap().serverResponse, 'warmed response');
assert.equal(image.loading, 'eager');
assert.equal(image.decoding, 'sync');
assert.equal(image.dataset.artworkReady, 'true');
listeners.get('pagehide')();
assert.deepEqual(JSON.parse(savedArtwork), [
  'http://localhost/remembered.jpg', 'http://localhost/poster.jpg',
]);
images = [{ getAttribute: () => 'http://%' }];
assert.doesNotThrow(swap); // broken artwork must not prevent navigation
entrance = true;
assert.equal(swap().shouldSwap, false);
assert.deepEqual(redirects, ['http://localhost/lists']);

// A full document promotes remembered images while parsing, then disconnects
// its observer. It does not need to wait for DOMContentLoaded to start them.
let inserted;
let disconnected = false;
context.document.readyState = 'loading';
context.document.documentElement = {};
context.MutationObserver = class {
  constructor(callback) { inserted = callback; }
  observe() {}
  disconnect() { disconnected = true; }
};
listeners.clear();
vm.runInNewContext(source, context);
const parsedImage = {
  dataset: {},
  nodeType: 1, matches: () => true, querySelectorAll: () => [],
  loading: 'lazy', decoding: 'auto', getAttribute: () => '/poster.jpg',
};
inserted([{ addedNodes: [parsedImage] }]);
assert.equal(parsedImage.loading, 'eager');
assert.equal(parsedImage.decoding, 'sync');
assert.equal(parsedImage.dataset.artworkReady, 'true');
const coldImages = Array.from({ length: 9 }, (_, index) => ({
  nodeType: 1, matches: () => true, querySelectorAll: () => [], dataset: {},
  loading: 'lazy', getAttribute: () => `/cold-${index}.jpg`,
}));
inserted([{ addedNodes: coldImages }]);
assert.equal(coldImages.filter(img => img.loading === 'eager').length, 7);
assert.equal(coldImages.filter(img => img.loading === 'lazy').length, 2);
// Parser records can include the same image twice; it only uses one slot.
inserted([{ addedNodes: [coldImages[8]] }]);
assert.equal(coldImages[8].loading, 'lazy');
listeners.get('DOMContentLoaded')();
assert.equal(disconnected, true);
"""
        result = subprocess.run(  # noqa: S603  # fixed argv and repository script
            [node, "-e", check],
            input=json.dumps({"source": source, "page": page}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_and_authenticated_pages_load_the_same_artwork_handler(self):
        """Public lists must retain artwork just like authenticated surfaces."""
        for authenticated in (True, False):
            with self.subTest(authenticated=authenticated):
                if authenticated:
                    self.client.force_login(self.user)
                else:
                    self.client.logout()
                response = self.client.get(
                    reverse("user_profile", args=[self.user.username])
                )
                self.assertContains(response, "/static/js/artwork-loading.js?")
