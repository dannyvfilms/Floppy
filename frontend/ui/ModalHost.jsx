import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

// One host per page for the track and add-to-list popups that cards open. The
// popups' server forms still close themselves by finding the nearest element
// with x-show="trackOpen" (or listsOpen) and setting that Alpine value, so the
// wrapper below keeps that contract and tells React when Alpine hid it.

export function openModal(spec) {
  window.dispatchEvent(new CustomEvent('floppy-open-modal', { detail: spec }));
}

const shells = {
  track: {
    key: 'trackOpen',
    outer: 'fixed inset-0 bg-black/50 flex items-center justify-center z-50',
    inner: 'modal-max-height overflow-y-auto px-4 md:px-0 relative z-60 w-full',
    style: { width: 'min(96vw, 72rem)' },
  },
  lists: {
    key: 'listsOpen',
    outer: 'fixed inset-0 bg-black/50 flex items-center justify-center z-50',
    inner: 'w-96 max-h-[90dvh] px-4 md:px-0 relative z-60',
    style: undefined,
  },
};

function Modal({ spec, onClose }) {
  const host = useRef(null);
  const shell = shells[spec.modal];
  useEffect(() => {
    // The container exists once this renders; htmx fills it with the server form.
    window.htmx?.ajax('GET', spec.url, { target: spec.target, swap: 'innerHTML', values: spec.vals });
    const node = host.current;
    const closed = () => onClose(spec.target);
    node.addEventListener('floppy-modal-closed', closed);
    const key = (event) => { if (event.key === 'Escape') closed(); };
    window.addEventListener('keydown', key);
    return () => { node.removeEventListener('floppy-modal-closed', closed); window.removeEventListener('keydown', key); };
  }, []);
  const scope = `{ ${shell.key}: true }`;
  return <div ref={host} x-data={scope} {...{ 'x-effect': `if (!${shell.key}) $el.dispatchEvent(new CustomEvent('floppy-modal-closed'))` }}>
    <div className={shell.outer} {...{ 'x-show': shell.key }}
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(spec.target); }}>
      <div className={shell.inner} style={shell.style}><div id={spec.target.slice(1)} /></div>
    </div>
  </div>;
}

export function ModalHost() {
  const [open, setOpen] = useState([]);
  useEffect(() => {
    const onOpen = (event) => setOpen((current) => (current.some((spec) => spec.target === event.detail.target)
      ? current : [...current, event.detail]));
    window.addEventListener('floppy-open-modal', onOpen);
    return () => window.removeEventListener('floppy-open-modal', onOpen);
  }, []);
  const close = (target) => setOpen((current) => current.filter((spec) => spec.target !== target));
  return <>{open.map((spec) => createPortal(<Modal key={spec.target} spec={spec} onClose={close} />, document.body))}</>;
}
