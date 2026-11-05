import React, { useEffect, useRef, useState } from 'react';
import { Spinner } from './controls';

// The header search form. Class names match the Django form it replaces, so the
// themes keep applying. Suggestions stay a server fragment: htmx fills
// #search-suggestions, and searchAutocomplete.js drives its keyboard handling.

function Icon({ children, className }) {
  return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

const fill = (template, media) => template.replace('%(media)s', media);

export function GlobalSearch({ props }) {
  const { action, query, mediaTypes, barcodeTypes, suggestionsUrl, labels } = props;
  const [type, setType] = useState(props.selectedType);
  const [open, setOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [barcodeError, setBarcodeError] = useState(null);
  const form = useRef(null);
  const input = useRef(null);
  const searchButton = useRef(null);
  const fileInput = useRef(null);
  const explicitSubmit = useRef(false);
  const isBarcodeType = barcodeTypes.includes(type.value);

  useEffect(() => { window.htmx?.process(form.current); }, []);
  useEffect(() => {
    const away = (event) => {
      if (!form.current?.contains(event.target)) {
        setOpen(false);
        const suggestions = document.getElementById('search-suggestions');
        if (suggestions) suggestions.innerHTML = '';
      }
    };
    const onKey = (event) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('click', away);
    window.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('click', away); window.removeEventListener('keydown', onKey); };
  }, []);

  function placeholder() {
    if (type.value === 'all') return labels.placeholderAll;
    const short = window.matchMedia('(max-width: 639px)').matches;
    return fill(short ? labels.placeholderShort : labels.placeholderLong, type.display);
  }

  function onSubmit(event) {
    const submitter = event.nativeEvent.submitter;
    if (submitter && !form.current.contains(submitter)) return;
    if (explicitSubmit.current) { explicitSubmit.current = false; return; }
    if (submitter && submitter === searchButton.current) return;
    if (!submitter && document.activeElement === input.current) return;
    event.preventDefault();
    event.stopPropagation();
  }

  function selectType(next) {
    setType(next);
    setOpen(false);
    if (input.current?.value.trim()) setTimeout(() => form.current.submit(), 0);
  }

  async function onBarcodeImage(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setScanning(true);
    setBarcodeError(null);
    try {
      if (!window.barcodeScannerUtils) throw new Error(labels.barcodeNotLoaded);
      const isbn = await window.barcodeScannerUtils.decodeBarcodeFromFile(file);
      if (isbn) {
        input.current.value = isbn;
        explicitSubmit.current = true;
        form.current.submit();
      } else {
        setBarcodeError(labels.barcodeUnreadable);
      }
    } catch (error) {
      setBarcodeError(labels.barcodeFailed + (error.message || labels.tryAgain));
    } finally {
      setScanning(false);
    }
  }

  function clearError() {
    setBarcodeError(null);
    if (fileInput.current) fileInput.current.value = '';
  }

  return <form ref={form} method="get" action={action} onSubmit={onSubmit}>
    <div className="flex">
      <div className="relative grow">
        <input ref={input} type="search" id="global-search" aria-label={labels.inputLabel} name="q"
          defaultValue={query} placeholder={placeholder()} autoComplete="off" role="combobox"
          aria-autocomplete="list" aria-expanded="false" aria-controls="search-suggestions"
          {...{ 'hx-get': suggestionsUrl, 'hx-trigger': 'keyup changed delay:250ms, search',
            'hx-target': '#search-suggestions', 'hx-swap': 'innerHTML', 'hx-include': "[name='media_type']" }}
          className={`w-full py-2 pl-10 ${isBarcodeType ? 'pr-10' : 'pr-4'} text-sm text-[var(--color-text-secondary)] bg-[var(--color-panel)] rounded-l-md focus:outline-none focus:ring-2 focus:ring-(--color-accent) focus:ring-inset placeholder-[var(--color-text-muted)]`} />
        <button ref={searchButton} type="submit" aria-label={labels.search}
          className="absolute left-2 top-1/2 transform -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-(--color-accent) rounded-sm cursor-pointer">
          <Icon className="w-5 h-5"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></Icon>
        </button>
        {isBarcodeType && <button type="button" disabled={scanning} title={labels.scan} aria-label={labels.scan}
          onClick={() => fileInput.current?.click()}
          className="absolute right-2 top-1/2 transform -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-(--color-accent) rounded-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
          {scanning
            ? <span className="block"><Spinner size={20} tone="muted" /></span>
            : <span className="block"><Icon className="w-5 h-5"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" /><circle cx="12" cy="13" r="3" /></Icon></span>}
        </button>}
        <input ref={fileInput} type="file" accept="image/*" className="hidden" onChange={onBarcodeImage} />
        <div id="search-suggestions" />
      </div>
      <input type="hidden" name="media_type" value={type.value} />
      <div className="relative">
        <button type="button" onClick={() => setOpen((value) => !value)} aria-haspopup="listbox" aria-expanded={open}
          className="flex items-center justify-between shrink-0 px-3 sm:px-4 py-2 text-sm text-[var(--color-text-secondary)] bg-[var(--color-panel)] rounded-r-md focus:outline-none focus:ring-2 focus:ring-(--color-accent) focus:ring-inset hover:bg-[var(--color-surface)] transition-colors duration-200 cursor-pointer">
          <span className="whitespace-nowrap max-[24rem]:sr-only">{type.display}</span>
          <Icon className="w-4 h-4 ml-2"><path d="m6 9 6 6 6-6" /></Icon>
        </button>
        {open && <ul className="global-search-menu absolute z-50 py-1 mt-12 overflow-auto text-sm text-[var(--color-text-secondary)] bg-[var(--color-surface)] rounded-md shadow-lg right-0 w-32">
          {mediaTypes.map((option) => <li key={option.value} onClick={() => selectType(option)}
            className="px-4 py-2 cursor-pointer hover:bg-[var(--color-surface-muted)] transition duration-150 ease-in-out">{option.display}</li>)}
        </ul>}
      </div>
    </div>
    {barcodeError && <div className="absolute z-50 mt-2 w-full max-w-2xl">
      <div className="flex items-center gap-2 rounded-md border px-3 py-2 shadow-lg toast-info">
        <Icon className="w-4 h-4 text-indigo-300 shrink-0"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></Icon>
        <p className="text-sm font-medium flex-1">{barcodeError}</p>
        <button type="button" onClick={clearError} aria-label={labels.dismiss}
          className="text-current opacity-70 hover:opacity-100 transition-opacity cursor-pointer">
          <Icon className="w-4 h-4"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></Icon>
        </button>
      </div>
    </div>}
  </form>;
}
