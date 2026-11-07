import React, { useEffect, useState } from 'react';
import { View } from 'react-native';
import { MediaCardActionHost } from './MediaCardActionHost';

// Keep the platform counterpart on the React Native renderer even though the
// shell itself is the shared action host.
void View;

// Native counterpart of the browser popup host. There is no DOM CustomEvent,
// Alpine or htmx here, so the same `openModal(spec)` / `ModalHost` contract
// resolves through a module-level listener owned by the mounted host instead
// of `window`. A spec keeps the browser fields (`modal`, `url`, `vals`,
// `target`) and may add `title`, `content` and `labels` for native. Server
// forms and URL fetches stay web-only; a spec without content opens the shared
// action host as an empty dismissible shell rather than silently failing.
//
// Unlike the browser host, which stacks one popup per target, native renders
// the most recently opened spec because stacked RN Modals are not reliable.

const listeners = new Set();

export function openModal(spec) {
  if (!spec || !spec.target) return;
  for (const listener of listeners) listener(spec);
}

export function ModalHost() {
  const [current, setCurrent] = useState(null);
  useEffect(() => {
    const onOpen = (spec) => setCurrent(spec);
    listeners.add(onOpen);
    return () => { listeners.delete(onOpen); };
  }, []);
  const close = () => setCurrent(null);
  return <MediaCardActionHost
    action={current ? { title: current.title || current.labels?.title || '' } : null}
    open={Boolean(current)}
    labels={current?.labels}
    onClose={close}>
    {current?.content || null}
  </MediaCardActionHost>;
}
