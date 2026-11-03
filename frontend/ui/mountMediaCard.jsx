import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { MediaCard } from './MediaCard';

// The server renders the whole legacy card inside the host. Before React takes
// the host over, lift out the three server-owned pieces (status chip, hover
// actions, rating) so the htmx and Alpine behaviour on them keeps working.
const sources = {
  status: '[id^="media-status-chip"]',
  overlay: '.media-card-overlay',
  rating: '[id^="media-card-rating"]',
};

// Bulk selection lives in the page's Alpine scope (selectMode, isItemSelected,
// toggleItemSelected). Mirror it here instead of keeping a second copy.
function useSelection(host, itemId) {
  const [state, setState] = useState({ active: false, selected: false });
  useEffect(() => {
    const Alpine = window.Alpine;
    if (itemId == null || !Alpine) return undefined;
    const runner = Alpine.effect(() => {
      const scope = Alpine.$data(host);
      setState({ active: !!scope.selectMode, selected: !!scope.isItemSelected?.(itemId) });
    });
    return () => Alpine.release(runner);
  }, [host, itemId]);
  if (itemId == null) return undefined;
  return { ...state, toggle: () => window.Alpine?.$data(host).toggleItemSelected(itemId) };
}

function Card({ host, props, slots }) {
  const selection = useSelection(host, props.model.bulkItemId);
  return <MediaCard model={props.model} slots={slots} labels={props.labels} selection={selection} />;
}

export function mountMediaCard(host, props) {
  const slots = {};
  if (props.model.layout === 'row') {
    for (const name of ['meta', 'actions']) slots[name] = host.querySelector(`[data-card-slot-source="${name}"]`);
  } else {
    for (const [name, selector] of Object.entries(sources)) slots[name] = host.querySelector(selector);
  }
  const restore = mountRoot(host, <Card host={host} props={props} slots={slots} />);
  // The release-year loader runs once per page or swap, often before this mount.
  window.loadVisibleReleaseYears?.();
  return () => { restore(); };
}
