// Keyboard navigation for the global search autocomplete dropdown.
//
// WAI-ARIA editable-combobox pattern: DOM focus never leaves the text input.
// Arrow keys move a visual highlight (tracked with aria-activedescendant) over
// the suggestions, so the user can keep typing at any moment. Enter opens the
// highlighted item; Enter with nothing highlighted falls through to the form's
// normal submit, which runs the online search. To get back to an online search
// after arrowing down, press Up past the first row (returns to the plain text
// field) or arrow down to the last row, which is the "Search online" action.
//
// Bind once: this script is re-evaluated on boosted (hx-boost) navigation.
if (!window.__floppySearchAutocompleteBound) {
window.__floppySearchAutocompleteBound = true;

const CONTAINER_ID = 'search-suggestions';
const INPUT_ID = 'global-search';
let activeIndex = -1;

function container() {
  return document.getElementById(CONTAINER_ID);
}

function input() {
  return document.getElementById(INPUT_ID);
}

function options() {
  const c = container();
  return c ? Array.from(c.querySelectorAll('[role="option"]')) : [];
}

function highlight(el, on) {
  if (!el) return;
  if (on) {
    el.style.backgroundColor = '#343a40';
    el.style.color = '#fff';
    el.setAttribute('aria-selected', 'true');
  } else {
    el.style.backgroundColor = '';
    el.style.color = '';
    el.removeAttribute('aria-selected');
  }
}

function setActive(index) {
  const opts = options();
  opts.forEach((el) => highlight(el, false));
  const inp = input();
  if (index < 0 || index >= opts.length) {
    activeIndex = -1;
    if (inp) inp.removeAttribute('aria-activedescendant');
    return;
  }
  activeIndex = index;
  const el = opts[index];
  if (!el.id) el.id = 'search-suggestion-' + index;
  highlight(el, true);
  if (inp) inp.setAttribute('aria-activedescendant', el.id);
  el.scrollIntoView({ block: 'nearest' });
}

function reset() {
  activeIndex = -1;
  const inp = input();
  if (inp) {
    inp.removeAttribute('aria-activedescendant');
    inp.setAttribute('aria-expanded', options().length > 0 ? 'true' : 'false');
  }
}

function clearPanel() {
  const c = container();
  if (c) c.innerHTML = '';
  reset();
}

document.addEventListener('keydown', (e) => {
  const inp = input();
  if (!inp || e.target !== inp) return;
  const opts = options();

  if (e.key === 'ArrowDown') {
    if (!opts.length) return;
    e.preventDefault();
    setActive(activeIndex + 1 >= opts.length ? opts.length - 1 : activeIndex + 1);
  } else if (e.key === 'ArrowUp') {
    if (!opts.length) return;
    e.preventDefault();
    // Up from the first row lands on -1 (plain text field, no highlight).
    setActive(activeIndex - 1);
  } else if (e.key === 'Enter') {
    if (activeIndex >= 0 && opts[activeIndex]) {
      const el = opts[activeIndex];
      e.preventDefault();
      if (el.hasAttribute('data-search-online') && inp.form && inp.form.requestSubmit) {
        // Run the online search using the input's live value.
        inp.form.requestSubmit();
      } else {
        window.location.href = el.getAttribute('href');
      }
    }
    // Nothing highlighted: let the form submit normally (online search).
  } else if (e.key === 'Escape') {
    if (opts.length) {
      e.preventDefault();
      clearPanel();
    }
  }
});

// Reset highlight state whenever a fresh batch of suggestions is swapped in.
document.addEventListener('htmx:afterSwap', (e) => {
  if (e.target && e.target.id === CONTAINER_ID) reset();
});
}
