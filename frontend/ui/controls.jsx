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

export function Button({ children, danger = false, secondary = false, ...props }) {
  return <button className={`ui-button${danger ? ' ui-button-danger' : ''}${secondary ? ' ui-button-secondary' : ''}`}
    {...props}>{children}</button>;
}

export function Field({ label, labelHidden = false, icon, id, ...props }) {
  const input = <input id={id} {...props} />;
  return <div className="ui-field"><label className={labelHidden ? 'ui-sr-only' : undefined} htmlFor={id}>{label}</label>
    {icon ? <div className="ui-input-with-icon">{input}<span aria-hidden="true">{icon}</span></div> : input}
  </div>;
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

export function Form({ action, csrf, returnTo, children, confirm, className = '', onSubmit }) {
  return <form action={action} method="post" className={`ui-form ${className}`} onSubmit={event => {
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

export function FeatureList({ items }) {
  return <ul className="ui-feature-list">{items.map(item => <li key={item.key}>
    <StatusIcon tone={item.tone} label={`${item.label}: ${item.status}`} />
    <div><span>{item.label}</span>{item.note && <p>{item.note}</p>}</div>
    {item.tone !== 'success' && <span className="ui-feature-state">{item.status}</span>}
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
