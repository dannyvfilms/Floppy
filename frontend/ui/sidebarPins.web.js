import { useEffect, useState } from 'react';

// The account's sidebar pins, shared with the sidebar and the Alpine pin buttons through
// `window.floppySidebarPins` and the `sidebar-pins-changed` event. Web only: the Expo app
// has no sidebar to pin to.
function readPins() {
  if (window.floppySidebarPins) return window.floppySidebarPins;
  let data = {};
  try { data = JSON.parse(document.getElementById('sidebar-pins-data')?.textContent || '{}'); } catch { data = {}; }
  window.floppySidebarPins = { nav: data?.nav || [], lists: data?.lists || [] };
  return window.floppySidebarPins;
}

const csrfToken = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

export function toggleListPin(pin) {
  const { nav, lists } = readPins();
  const others = lists.filter(entry => entry.id !== pin.id);
  const next = { nav, lists: lists.some(entry => entry.id === pin.id) ? others : [...others, { id: pin.id, name: pin.name, url: pin.url }] };
  window.floppySidebarPins = next;
  window.dispatchEvent(new Event('sidebar-pins-changed'));
  fetch(pin.pinsUrl, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: JSON.stringify(next),
  }).catch(() => { /* The pin still applies to this page. */ });
}

export function useListPinned(id) {
  const [pinned, setPinned] = useState(() => readPins().lists.some(entry => entry.id === id));
  useEffect(() => {
    const update = () => setPinned(readPins().lists.some(entry => entry.id === id));
    update();
    window.addEventListener('sidebar-pins-changed', update);
    return () => window.removeEventListener('sidebar-pins-changed', update);
  }, [id]);
  return pinned;
}
