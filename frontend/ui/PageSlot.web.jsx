import React, { useLayoutEffect, useRef } from 'react';
import { View } from 'react-native';

// Browser slot host for the shared page compositions.
//
// Server-rendered regions keep their markup, Alpine state and htmx endpoints
// (filters, tables, modals); the shared view owns where the region appears.
// Nodes are adopted only after a successful React render, the source element
// stays as the no-JavaScript fallback, and every node returns to it on unmount.
export function PageSlot({ source, style }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const target = ref.current;
    if (!source || !target) return undefined;
    const nodes = [...source.childNodes];
    if (!nodes.length) return undefined;
    target.replaceChildren(...nodes);
    source.hidden = true;
    return () => {
      source.hidden = false;
      source.replaceChildren(...nodes);
      target.replaceChildren();
    };
  }, [source]);
  // `display: contents` keeps the server nodes in the page's original layout
  // flow and avoids a new stacking context, so the Alpine menus that belong to
  // an adopted region still paint above the table/grid region below them.
  return <View ref={ref} style={style || styles.slot} />;
}

const styles = { slot: { display: 'contents' } };

// Page adapters mark each server-owned region with `data-page-slot`. The host
// lives inside the region scope so Alpine ancestors stay intact after adoption.
export function collectPageSlots(host) {
  const scope = host.closest('[data-page-slot-scope]') || host.parentElement;
  const slots = {};
  scope?.querySelectorAll('[data-page-slot]').forEach((node) => {
    slots[node.dataset.pageSlot] = node;
  });
  return slots;
}
