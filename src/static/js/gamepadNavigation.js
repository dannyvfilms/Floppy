// Game controller navigation (issue #1871).
//
// Lets a gamepad move through the page like a TV remote: the D-pad or left
// stick moves focus to the nearest control in that direction, A presses it,
// B closes the open dialog (or goes back), the right stick scrolls, and Start
// jumps to search. It only does anything once a controller has been used, so
// keyboard, mouse and touch behave exactly as before.
//
// Bind once: this script is re-evaluated on boosted (hx-boost) navigation.
(function () {
  var FOCUSABLE = [
    'a[href]', 'button', 'input:not([type="hidden"])', 'select', 'textarea',
    'summary', '[tabindex]:not([tabindex="-1"])', '[role="button"]',
    '[role="link"]', '[role="menuitem"]', '[role="tab"]', '[role="option"]',
  ].join(',');
  var DIALOGS = 'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]';
  var DEADZONE = 0.5;
  var SCROLL_DEADZONE = 0.2;
  var FIRST_REPEAT_MS = 400;
  var REPEAT_MS = 130;
  var BUTTON = { A: 0, B: 1, START: 9, UP: 12, DOWN: 13, LEFT: 14, RIGHT: 15 };

  // Pure helpers (no DOM), exported for tests.

  // Left stick or D-pad -> 'up' | 'down' | 'left' | 'right' | null.
  function directionFrom(axes, buttons) {
    var pressed = function (index) { return !!(buttons[index] && buttons[index].pressed); };
    if (pressed(BUTTON.UP)) return 'up';
    if (pressed(BUTTON.DOWN)) return 'down';
    if (pressed(BUTTON.LEFT)) return 'left';
    if (pressed(BUTTON.RIGHT)) return 'right';
    var x = axes[0] || 0;
    var y = axes[1] || 0;
    if (Math.max(Math.abs(x), Math.abs(y)) < DEADZONE) return null;
    if (Math.abs(x) > Math.abs(y)) return x > 0 ? 'right' : 'left';
    return y > 0 ? 'down' : 'up';
  }

  // Pick the candidate rect nearest to `from` in `direction`. Distance along
  // the direction counts once, distance across it counts double, so a control
  // straight ahead beats one that is closer but off to the side.
  function pickNext(from, candidates, direction) {
    var cx = from.left + from.width / 2;
    var cy = from.top + from.height / 2;
    var best = null;
    var bestScore = Infinity;
    candidates.forEach(function (candidate) {
      var rect = candidate.rect;
      var dx = rect.left + rect.width / 2 - cx;
      var dy = rect.top + rect.height / 2 - cy;
      var along = direction === 'right' ? dx : direction === 'left' ? -dx : direction === 'down' ? dy : -dy;
      var across = direction === 'left' || direction === 'right' ? Math.abs(dy) : Math.abs(dx);
      // Must be ahead of the current control, not just overlapping it.
      var aheadEdge = direction === 'right' ? rect.left >= from.left + from.width / 2
        : direction === 'left' ? rect.left + rect.width <= from.left + from.width / 2
          : direction === 'down' ? rect.top >= from.top + from.height / 2
            : rect.top + rect.height <= from.top + from.height / 2;
      if (along <= 1 || !aheadEdge) return;
      var score = along + across * 2;
      if (score < bestScore) {
        bestScore = score;
        best = candidate;
      }
    });
    return best;
  }

  var api = { directionFrom: directionFrom, pickNext: pickNext, BUTTON: BUTTON };
  window.FloppyGamepadNav = api;
  if (window.__floppyGamepadNavBound) return;
  window.__floppyGamepadNavBound = true;

  // Browser side.

  var style = document.createElement('style');
  style.textContent = 'html.gamepad-nav :focus { outline: 3px solid var(--color-accent, #4a9eff) !important; outline-offset: -3px !important; }';
  (document.head || document.documentElement).appendChild(style);

  function visible(el) {
    if (!el.isConnected || el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    var rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return false;
    var cs = window.getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    // Controls kept in the page but faded out until hover (media card actions)
    // are not there yet, so focus must not land on them.
    for (var node = el; node && node.nodeType === 1; node = node.parentElement) {
      if (window.getComputedStyle(node).opacity === '0') return false;
    }
    return true;
  }

  function topDialog() {
    // A dialog wrapper can be zero-sized when its panel is positioned out of
    // flow, so it counts as open when it holds a visible control.
    var all = Array.prototype.filter.call(document.querySelectorAll(DIALOGS), function (dialog) {
      return Array.prototype.some.call(dialog.querySelectorAll(FOCUSABLE), visible);
    });
    return all.length ? all[all.length - 1] : null;
  }

  function candidates() {
    var scope = topDialog() || document;
    return Array.prototype.filter.call(scope.querySelectorAll(FOCUSABLE), visible).map(function (el) {
      return { el: el, rect: el.getBoundingClientRect() };
    }).filter(function (c) {
      // A full-screen backdrop that closes a menu is not a control to land on.
      return !window.innerWidth || c.rect.width * c.rect.height < window.innerWidth * window.innerHeight * 0.6;
    });
  }

  function move(direction) {
    var all = candidates();
    if (!all.length) return;
    var active = document.activeElement;
    var current = active && active !== document.body && visible(active) && all.some(function (c) { return c.el === active; })
      ? active : null;
    var target;
    if (!current) {
      // Nothing focused yet: start with the first control on screen.
      var onScreen = all.filter(function (c) {
        return c.rect.bottom > 0 && c.rect.top < window.innerHeight;
      });
      var pool = onScreen.length ? onScreen : all;
      target = pool.reduce(function (a, b) {
        return b.rect.top < a.rect.top - 1 || (Math.abs(b.rect.top - a.rect.top) <= 1 && b.rect.left < a.rect.left) ? b : a;
      });
    } else {
      target = pickNext(current.getBoundingClientRect(), all.filter(function (c) { return c.el !== current; }), direction);
    }
    if (target) {
      target.el.focus({ preventScroll: true });
      target.el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    } else if (!topDialog() && (direction === 'up' || direction === 'down')) {
      window.scrollBy({ top: (direction === 'down' ? 1 : -1) * window.innerHeight * 0.6, behavior: 'smooth' });
    }
  }

  function press() {
    var el = document.activeElement;
    if (el && el !== document.body) el.click();
  }

  function back() {
    var dialog = topDialog();
    if (dialog) {
      var close = dialog.querySelector('[aria-label="Close"], [data-modal-close], [data-dismiss], .modal-close');
      if (close) { close.click(); return; }
      var escape = { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true };
      (document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', escape));
      document.dispatchEvent(new KeyboardEvent('keydown', escape));
      return;
    }
    // Popups that are not dialogs (rating popup, search suggestions) close on
    // Escape. Try that first; leave the page only if nothing on it reacted.
    var changed = false;
    var watcher = new MutationObserver(function () { changed = true; });
    watcher.observe(document.body, { childList: true, subtree: true });
    var esc = { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true };
    (document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', esc));
    window.setTimeout(function () {
      watcher.disconnect();
      if (!changed && window.history.length > 1) window.history.back();
    }, 120);
  }

  function search() {
    var input = document.getElementById('global-search');
    if (input) { input.focus(); input.select(); }
  }

  var held = {};
  var rafId = null;

  function active(on) {
    document.documentElement.classList.toggle('gamepad-nav', on);
  }

  // Fires on press, and again while held when `repeats` (the D-pad and stick).
  // A, B and Start fire once per press so a held button cannot press twice.
  function edge(key, isDown, now, action, repeats) {
    if (!isDown) { delete held[key]; return; }
    var state = held[key];
    if (!state) {
      held[key] = { next: now + FIRST_REPEAT_MS };
      action();
    } else if (repeats && now >= state.next) {
      state.next = now + REPEAT_MS;
      action();
    }
  }

  function tick(now) {
    rafId = null;
    var pads = (navigator.getGamepads ? navigator.getGamepads() : []) || [];
    var any = false;
    Array.prototype.forEach.call(pads, function (pad) {
      if (!pad || !pad.connected) return;
      any = true;
      var direction = directionFrom(pad.axes, pad.buttons);
      if (direction) active(true);
      ['up', 'down', 'left', 'right'].forEach(function (name) {
        edge(pad.index + name, direction === name, now, function () { move(name); }, true);
      });
      var down = function (i) { return !!(pad.buttons[i] && pad.buttons[i].pressed); };
      edge(pad.index + 'A', down(BUTTON.A), now, function () { active(true); press(); });
      edge(pad.index + 'B', down(BUTTON.B), now, function () { active(true); back(); });
      edge(pad.index + 'S', down(BUTTON.START), now, function () { active(true); search(); });
      var scrollY = pad.axes[3] || 0;
      if (Math.abs(scrollY) > SCROLL_DEADZONE) window.scrollBy(0, scrollY * 24);
    });
    if (any && !document.hidden) rafId = window.requestAnimationFrame(tick);
  }

  function start() {
    if (rafId === null) rafId = window.requestAnimationFrame(tick);
  }

  window.addEventListener('gamepadconnected', start);
  window.addEventListener('gamepaddisconnected', function () { held = {}; });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) start(); });
  // Going back to mouse or touch hides the controller focus ring again.
  ['pointerdown', 'mousemove'].forEach(function (type) {
    document.addEventListener(type, function () { active(false); }, { passive: true });
  });
  if (navigator.getGamepads && Array.prototype.some.call(navigator.getGamepads() || [], Boolean)) start();
})();
