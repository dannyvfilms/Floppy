import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Chip as NativeChip } from '../settings/Chip';
import { SettingsCard } from '../settings/SettingsCard';
import { webPalette } from '../settings/webPalette';

export function Chip({ tone = 'neutral', ...props }) {
  return <div className="settings-chip" data-tone={tone}><NativeChip {...props} palette={webPalette} /></div>;
}

export function ToggleChip({ value, onChange, offLabel, onLabel, label }) {
  return <Chip label={value ? onLabel : offLabel} tone={value ? 'info' : 'neutral'}
    accessibilityLabel={label || `${offLabel} / ${onLabel}`} pressed={value}
    onPress={() => onChange(!value)} />;
}

export function Card({ title, tone = 'neutral', badge, infoLabel, onInfo, href, tooltip, headerAction, children }) {
  const Container = href ? 'a' : 'section';
  return <Container className={`settings-card${href ? ' ui-card-link' : ''}`} data-tone={tone} href={href} title={tooltip} aria-label={href ? title : undefined}>
    <SettingsCard title={title} badge={badge} info_label={infoLabel} onInfo={onInfo}
      headerAction={headerAction} palette={webPalette} framed={false}>{children}</SettingsCard>
  </Container>;
}

export function Tooltip({ label, text }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const button = useRef(null), popup = useRef(null);
  const tooltipId = React.useId();
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const anchor = button.current?.getBoundingClientRect(), box = popup.current?.getBoundingClientRect();
      if (!anchor || !box) return;
      const left = Math.max(8, Math.min(window.innerWidth - box.width - 8, anchor.left + anchor.width / 2 - box.width / 2));
      const preferred = anchor.top - box.height - 8;
      const top = Math.max(8, Math.min(window.innerHeight - box.height - 8, preferred < 8 ? anchor.bottom + 8 : preferred));
      setPosition({ left, top });
    }
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [open]);
  return <span className="ui-tooltip-trigger">
    <button type="button" ref={button} aria-label={label} aria-describedby={open ? tooltipId : undefined}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (document.activeElement !== button.current) setOpen(false); }}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => setOpen(true)}
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); } }}>
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8h.01" /></svg>
    </button>
    {open && createPortal(<span role="tooltip" id={tooltipId} ref={popup} className="ui-tooltip-popup"
      style={{ left: position.left, top: position.top }}>{text}</span>, document.body)}
  </span>;
}

export function ActivityList({ children }) {
  return <div className="ui-activity-list" tabIndex={0}>{children}</div>;
}

export function CardGrid({ children, auto = false, alignStart = false, className = '' }) {
  return <div className={`ui-card-grid${auto ? ' ui-card-grid-auto' : ''}${alignStart ? ' ui-card-grid-start' : ''} ${className}`}>{children}</div>;
}

export function Button({ children, danger = false, secondary = false, href, ...props }) {
  const Element = href ? 'a' : 'button';
  return <Element href={href} className={`ui-button${danger ? ' ui-button-danger' : ''}${secondary ? ' ui-button-secondary' : ''}`}
    {...props}>{children}</Element>;
}

export function Field({ label, labelHidden = false, icon, id, ...props }) {
  const input = <input id={id} {...props} />;
  return <div className="ui-field"><label className={labelHidden ? 'ui-sr-only' : undefined} htmlFor={id}>{label}</label>
    {icon ? <div className="ui-input-with-icon">{input}<span aria-hidden="true">{icon}</span></div> : input}
  </div>;
}

// Free-text field that suggests existing names as you type and offers to create a new one inline.
export function ComboField({ label, id, value, options, onChange, onCommit, createLabel, disabled, placeholder, maxLength }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const host = useRef(null);
  const typed = value.trim(), query = typed.toLocaleLowerCase();
  const items = options.filter(name => name.toLocaleLowerCase().includes(query)).map(name => ({ name, label: name }));
  if (typed && !options.some(name => name.toLocaleLowerCase() === query)) items.push({ name: typed, label: createLabel(typed) });
  function choose(item) { onChange(item.name); onCommit(item.name); setOpen(false); }
  function keyDown(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) { setOpen(true); return; }
      setActive((active + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length);
    } else if (event.key === 'Enter' && open && items[active]) { event.preventDefault(); choose(items[active]); }
    else if (event.key === 'Escape') setOpen(false);
  }
  return <div className="ui-field" ref={host} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) { setOpen(false); onCommit(value); }
  }}><label htmlFor={id}>{label}</label>
    <div className="ui-select">
      <input id={id} type="text" role="combobox" autoComplete="off" aria-expanded={open && items.length > 0} aria-controls={`${id}-options`}
        aria-autocomplete="list" value={value} placeholder={placeholder} maxLength={maxLength} disabled={disabled}
        onChange={event => { onChange(event.target.value); setActive(0); setOpen(true); }}
        onFocus={() => setOpen(true)} onKeyDown={keyDown} />
      {open && items.length > 0 && <div id={`${id}-options`} role="listbox" aria-label={label} className="ui-select-options">
        {items.map((item, index) => <button key={item.name} type="button" role="option" tabIndex={-1} aria-selected={index === active}
          onMouseDown={event => event.preventDefault()} onClick={() => choose(item)}>{item.label}</button>)}
      </div>}
    </div>
  </div>;
}

// Native file input remains keyboard and screen-reader accessible.
export function FilePicker({ label, onChange, ...props }) {
  return <label className="ui-button ui-file-picker">
    <input className="ui-sr-only" type="file" onChange={onChange} {...props} />
    <span>{label}</span>
  </label>;
}

export function SelectField({ label, labelHidden = false, id, options, value, onChange, name, disabled, variant = 'preference' }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const host = useRef(null), trigger = useRef(null), search = useRef({ text: '', time: 0 });
  const selected = Math.max(0, options.findIndex(option => option.value === value));
  useEffect(() => {
    if (!open) return;
    const close = event => { if (!host.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);
  useEffect(() => {
    if (open) host.current?.querySelector(`[data-option-index="${active}"]`)?.focus();
  }, [open, active]);
  function choose(index) {
    if (options[index]?.disabled) return;
    onChange?.({ target: { name, value: options[index].value } });
    setOpen(false);
    trigger.current?.focus();
  }
  function keyDown(event) {
    const enabled = options.map((option, index) => option.disabled ? -1 : index).filter(index => index >= 0);
    if (!enabled.length) return;
    if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
    else if (event.key === 'Tab') setOpen(false);
    else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const current = enabled.indexOf(open ? active : selected);
      const next = event.key === 'Home' ? enabled[0] : event.key === 'End' ? enabled.at(-1) :
        enabled[(current + (event.key === 'ArrowDown' ? 1 : -1) + enabled.length) % enabled.length];
      setActive(next); setOpen(true);
    } else if (event.key.length === 1 && event.key !== ' ' && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      const now = Date.now();
      search.current = { text: (now - search.current.time < 700 ? search.current.text : '') + event.key.toLocaleLowerCase(), time: now };
      const match = enabled.find(index => options[index].label.toLocaleLowerCase().startsWith(search.current.text));
      if (match !== undefined) { setActive(match); setOpen(true); }
    }
  }
  return <div className="ui-field" ref={host} onKeyDown={keyDown} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }}><label id={`${id}-label`} className={labelHidden ? 'ui-sr-only' : undefined} htmlFor={id}>{label}</label>
    <div className={`ui-select${variant === 'filter' ? ' ui-select-filter' : ''}`}>
      <button id={id} ref={trigger} type="button" role="combobox" className="ui-select-trigger" disabled={disabled}
        aria-labelledby={`${id}-label`} aria-expanded={open} aria-haspopup="listbox" aria-controls={`${id}-options`}
        onClick={() => { setActive(selected); setOpen(!open); }}>
        {variant === 'filter' && <svg className="ui-filter-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" /></svg>}
        <span>{options[selected]?.label}</span>
      </button>
      <svg className="ui-select-chevron" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m6 9 6 6 6-6" />
      </svg>
      {open && <div id={`${id}-options`} role="listbox" aria-labelledby={`${id}-label`} className="ui-select-options">
        {options.map((option, index) => <button key={option.value} type="button" role="option" tabIndex={-1}
          data-option-index={index} aria-selected={option.value === value} disabled={option.disabled}
          onClick={() => choose(index)}>{option.label}</button>)}
      </div>}
    </div>
    {name && <input type="hidden" name={name} value={value} disabled={disabled} />}
  </div>;
}

export function FilterDropdown(props) {
  return <SelectField {...props} labelHidden variant="filter" />;
}

export function Form({ action, csrf, returnTo, children, confirm, className = '', onSubmit, encType, id }) {
  return <form id={id} action={action} method="post" encType={encType} className={`ui-form ${className}`} onSubmit={event => {
    if (confirm && !window.confirm(confirm)) { event.preventDefault(); return; }
    onSubmit?.(event);
  }}>
    <input type="hidden" name="csrfmiddlewaretoken" value={csrf} />
    {returnTo && <input type="hidden" name="next" value={returnTo} />}
    {children}
  </form>;
}

export function Dialog({ open, title, closeLabel, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement;
    const dialog = ref.current;
    dialog.showModal();
    return () => { dialog.close(); if (trigger?.isConnected) trigger.focus(); };
  }, [open]);
  return <dialog ref={ref} className="ui-dialog" aria-label={title}
    onCancel={event => { event.preventDefault(); onClose(); }}
    onClick={event => { if (event.target === ref.current) onClose(); }}>
    <div className="ui-dialog-content">
      <div className="ui-heading"><h3>{title}</h3>
        <Button type="button" secondary aria-label={closeLabel} onClick={onClose} autoFocus>×</Button>
      </div>
      {children}
    </div>
  </dialog>;
}

export function Tabs({ items, selected, label }) {
  return <nav className="ui-tabs" aria-label={label}>{items.map(item =>
    <a key={item.key} href={item.url} aria-current={selected === item.key ? 'page' : undefined}>{item.label}</a>)}</nav>;
}

export function FilterToolbar({ children, ...props }) {
  return <form className="ui-filter-toolbar" {...props}>{children}</form>;
}

export function CatalogGrid({ children, className = '', ...props }) {
  return <div className="ui-catalog"><div className={`ui-catalog-grid ${className}`} {...props}>{children}</div></div>;
}

export function StatusIcon({ tone = 'neutral', label }) {
  return <span className={`ui-status-icon ui-status-${tone}`} role="img" aria-label={label} title={label}>
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      {tone === 'success' ? <path d="m8 12 3 3 5-6" /> : tone === 'warning' ? <path d="M12 7v6m0 4h.01" /> : <path d="M8 12h8" />}
    </svg>
  </span>;
}

// Shared media-type icons mirror the app's existing navigation glyphs.
export function MediaIcon({ type }) {
  const shapes = {
    tv: <><rect width="20" height="15" x="2" y="7" rx="2" /><path d="m17 2-5 5-5-5" /></>,
    movie: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4" /></>,
    anime: <><circle cx="12" cy="12" r="10" /><path d="m10 8 6 4-6 4z" /></>,
    book: <><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5Zm0 0A2.5 2.5 0 0 1 6.5 17H20" /></>,
    manga: <><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7zM14 2v4a2 2 0 0 0 2 2h4M8 13h8M8 17h8" /></>,
    comic: <><rect x="3" y="3" width="8" height="18" rx="1" /><path d="M7 3v18m4-16 4-2 6 16-4 2z" /></>,
    game: <><path d="M7 5h10a4 4 0 0 1 4 3l1 8a3 3 0 0 1-5 2l-2-2H9l-2 2a3 3 0 0 1-5-2l1-8a4 4 0 0 1 4-3zM6 11h4M8 9v4m7-1h.01M18 10h.01" /></>,
    boardgame: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1" /><circle cx="16" cy="16" r="1" /><path d="M16 8h.01M8 16h.01" /></>,
    music: <><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></>,
    podcast: <><rect x="9" y="1" width="6" height="14" rx="3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2m7 9v4m-4 0h8" /></>,
    video: <><rect x="2" y="5" width="20" height="14" rx="3" /><path d="m10 9 5 3-5 3z" /></>,
  };
  return <svg className="ui-media-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{shapes[type] || <circle cx="12" cy="12" r="9" />}</svg>;
}

export function FeatureList({ items }) {
  return <ul className="ui-feature-list">{items.map(item => <li key={item.key}>
    <StatusIcon tone={item.tone} label={`${item.label}: ${item.status}`} />
    <div><span>{item.label}</span>{item.note && <p>{item.note}</p>}
      {item.tone !== 'success' && <p className="ui-feature-state">{item.status}</p>}
    </div>
  </li>)}</ul>;
}

export function CatalogCard({ title, description, logo, href, label, attention, status, pinned, pinLabel, onPin, pinDisabled }) {
  return <div className="ui-catalog-item"><a className="ui-catalog-card" href={href} aria-label={label || title}>
    <div className="ui-catalog-card-heading"><div>{logo && <img src={logo} alt="" />}<h3>{title}</h3></div>
      {status ? <StatusIcon {...status} /> : attention && <span className="ui-catalog-attention" role="img" aria-label={attention} title={attention}>⚠</span>}
    </div>
    <p>{description}</p>
  </a>{onPin && <button className="ui-catalog-pin" type="button" aria-label={pinLabel} aria-pressed={pinned}
    disabled={pinDisabled} onClick={onPin} title={pinLabel}>
    <svg aria-hidden="true" viewBox="0 0 24 24" fill={pinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 3 2.8 5.7L21 9.6l-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3z" />
    </svg>
  </button>}</div>;
}

// A labelled on/off setting that posts like a native checkbox.
export function ToggleRow({ id, name, label, help, defaultChecked, tone, disabled }) {
  return <div className="ui-toggle-row" data-tone={tone}>
    <label htmlFor={id}><span>{label}</span>{help && <small>{help}</small>}</label>
    <input id={id} type="checkbox" name={name} defaultChecked={defaultChecked} disabled={disabled} />
  </div>;
}
