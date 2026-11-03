import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ListsForm } from './ListsForm';

// One host per page for the track and add-to-list popups that cards open. The
// add-to-lists form is React-owned (ListsForm). The track popup's server form
// still closes itself by finding the nearest element
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

// React-owned popup: the overlay, Escape, focus return and scroll are handled
// here and the body is a React form that closes itself through onClose.
function ReactModal({ spec, onClose }) {
  const shell = shells[spec.modal];
  useEffect(() => {
    const trigger = document.activeElement;
    const key = (event) => { if (event.key === 'Escape') onClose(spec.target); };
    window.addEventListener('keydown', key);
    return () => { window.removeEventListener('keydown', key); if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return <div className={shell.outer} role="dialog" aria-modal="true" aria-labelledby="ui-modal-title" data-floppy-modal=""
    onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(spec.target); }}>
    <div className={shell.inner} style={shell.style}>
      <ListsForm url={spec.url} vals={spec.vals} labels={spec.labels || {}} targetId={spec.target.slice(1)} onClose={() => onClose(spec.target)} />
    </div>
  </div>;
}

function Modal({ spec, onClose }) {
  const host = useRef(null);
  const shell = shells[spec.modal];
  useEffect(() => {
    // The container exists once this renders; htmx fills it with the server form.
    window.htmx?.ajax('GET', spec.url, { target: spec.target, swap: 'innerHTML', values: spec.vals });
    const node = host.current;
    let timer;
    // Alpine hides the popup the moment its form submits. Keep the form in the
    // document until htmx has its response, or the response events (card
    // refresh, toast, closeModal) fire from a detached element and are lost.
    const closed = () => {
      clearTimeout(timer);
      const started = Date.now();
      const settle = () => {
        if (node.querySelector('.htmx-request') && Date.now() - started < 15000) timer = setTimeout(settle, 100);
        else onClose(spec.target);
      };
      timer = setTimeout(settle, 50);
    };
    node.addEventListener('floppy-modal-closed', closed);
    const key = (event) => { if (event.key === 'Escape') closed(); };
    window.addEventListener('keydown', key);
    return () => { clearTimeout(timer); node.removeEventListener('floppy-modal-closed', closed); window.removeEventListener('keydown', key); };
  }, []);
  const scope = `{ ${shell.key}: true }`;
  return <div ref={host} data-floppy-modal="" x-data={scope} {...{ 'x-effect': `if (!${shell.key}) $el.dispatchEvent(new CustomEvent('floppy-modal-closed'))` }}>
    <div className={shell.outer} {...{ 'x-show': shell.key }}
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(spec.target); }}>
      <div className={shell.inner} style={shell.style}><div id={spec.target.slice(1)} /></div>
    </div>
  </div>;
}

export function ModalHost() {
  const [open, setOpen] = useState([]);
  useEffect(() => {
    // Reopening a popup whose form is still finishing a save mounts a fresh one.
    const onOpen = (event) => setOpen((current) => [...current.filter((spec) => spec.target !== event.detail.target), event.detail]);
    window.addEventListener('floppy-open-modal', onOpen);
    return () => window.removeEventListener('floppy-open-modal', onOpen);
  }, []);
  const close = (target) => setOpen((current) => current.filter((spec) => spec.target !== target));
  return <>{open.map((spec) => createPortal(spec.modal === 'lists'
    ? <ReactModal key={spec.target} spec={spec} onClose={close} />
    : <Modal key={spec.target} spec={spec} onClose={close} />, document.body))}</>;
}
