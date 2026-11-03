import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

// The signed-in sidebar. Class names match the Django sidebar it replaces, so
// every theme keeps applying. Pins, pinned lists and group open states keep the
// same localStorage keys the page's list-pin buttons and saved-view scripts use.

const camel = (name) => name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());

function Shape({ node }) {
  const props = {};
  for (const [name, value] of Object.entries(node.attrs)) if (name !== 'class') props[camel(name)] = value;
  return React.createElement(node.tag, props, ...node.children.map((child, index) => <Shape key={index} node={child} />));
}

export function Icon({ spec, className }) {
  return <svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox={spec.viewBox}
    fill={spec.root.fill} stroke={spec.root.stroke} strokeWidth={spec.root['stroke-width']}
    strokeLinecap={spec.root['stroke-linecap']} strokeLinejoin={spec.root['stroke-linejoin']} className={className} aria-hidden="true">
    {spec.children.map((child, index) => <Shape key={index} node={child} />)}
  </svg>;
}

const rowClass = (active) => `transition-colors duration-200 text-sm ${active
  ? 'text-[var(--color-text)] bg-[var(--color-border)]'
  : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-hover-dim)]'}`;
const iconClass = (active, size = 'w-5 h-5') => `${size}${active ? ' text-[var(--color-link)]' : ''}`;
const hxBoost = { 'hx-boost': 'true' };
const fine = 'pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:focus:opacity-100';
const iconButton = 'p-1 rounded-md text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-hover-dim)] cursor-pointer';

function readJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    return value ?? fallback;
  } catch { return fallback; }
}
const writeJson = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Works without storage. */ } };
const readOpen = (key) => { try { return localStorage.getItem(`floppy:saved-views-open:${key}`); } catch { return null; } };
const writeOpen = (key, open) => { try { localStorage.setItem(`floppy:saved-views-open:${key}`, open ? '1' : '0'); } catch { /* Same. */ } };

// A small menu that floats over the page, closing on outside click, Escape, scroll and resize.
function Popup({ anchor, onClose, children, width = 176 }) {
  const [style, setStyle] = useState(null);
  const panel = useRef(null);
  useLayoutEffect(() => {
    const rect = anchor.current.getBoundingClientRect();
    setStyle({ left: Math.max(8, rect.right - width),
      ...(rect.top >= 48 ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }) });
  }, [anchor, width]);
  useEffect(() => {
    const away = (event) => { if (!panel.current?.contains(event.target) && !anchor.current?.contains(event.target)) onClose(); };
    const key = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('click', away);
    window.addEventListener('keydown', key);
    window.addEventListener('scroll', onClose, true);
    window.addEventListener('resize', onClose);
    return () => {
      document.removeEventListener('click', away);
      window.removeEventListener('keydown', key);
      window.removeEventListener('scroll', onClose, true);
      window.removeEventListener('resize', onClose);
    };
  }, [anchor, onClose]);
  return createPortal(<div ref={panel} className="fixed z-50 bg-[var(--color-surface-strong)] rounded-md shadow-lg border border-gray-700"
    style={{ ...style, width }}>{children}</div>, document.body);
}

const menuButton = 'w-full px-3 py-2 text-left text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)] cursor-pointer';

function PinMenu({ pinKey, pinned, onToggle, model }) {
  const [open, setOpen] = useState(false);
  const button = useRef(null);
  return <div className="relative shrink-0 mr-2">
    <button ref={button} type="button" className={`${iconButton} ${open ? 'pointer-fine:opacity-100' : fine}`}
      aria-expanded={open} aria-label={model.labels.navOptions} onClick={() => setOpen((value) => !value)}>
      <Icon spec={model.icons.ellipsis} className="w-4 h-4" />
    </button>
    {open && <Popup anchor={button} onClose={() => setOpen(false)}>
      <button type="button" className={menuButton} onClick={() => { onToggle(pinKey); setOpen(false); }}>
        {pinned ? model.labels.unpin : model.labels.pin}
      </button>
    </Popup>}
  </div>;
}

function Link({ item, pins, model }) {
  return <li>
    <div className="group relative flex items-center">
      <a href={item.href} className={`flex flex-1 min-w-0 items-center space-x-3 px-4 py-2 rounded-md ${rowClass(item.active)}`}>
        <Icon spec={item.icon} className={iconClass(item.active)} />
        <span>{item.label}</span>
      </a>
      {item.pinKey && <PinMenu pinKey={item.pinKey} pinned={pins.isPinned(item.pinKey)} onToggle={pins.toggle} model={model} />}
    </div>
  </li>;
}

function SavedViewGroup({ item, pins, model }) {
  const initial = item.views.some((view) => view.current) || readOpen(item.key) === '1';
  const [open, setOpen] = useState(initial);
  const [reordering, setReordering] = useState(false);
  const [views, setViews] = useState(item.views);
  const [menuFor, setMenuFor] = useState(null);
  const list = useRef(null);
  const sortable = useRef(null);
  const toggle = () => { setOpen(!open); writeOpen(item.key, !open); };

  useEffect(() => {
    if (!reordering || !list.current || !window.Sortable) return undefined;
    sortable.current = window.Sortable.create(list.current, {
      animation: 150, draggable: '[data-saved-view-id]', handle: '.saved-view-drag-handle',
      // React owns these rows: put the dragged one back and let state reorder it.
      onEnd: (event) => {
        const { item: row, from, oldIndex, newIndex } = event;
        if (oldIndex === newIndex) return;
        from.removeChild(row);
        from.insertBefore(row, from.children[oldIndex] || null);
        setViews((current) => {
          const next = [...current];
          next.splice(newIndex, 0, next.splice(oldIndex, 1)[0]);
          return next;
        });
      },
    });
    return () => { sortable.current?.destroy(); sortable.current = null; };
  }, [reordering]);

  function finishReorder() {
    const body = new URLSearchParams();
    body.append('media_type', item.key);
    views.forEach((view) => body.append('ids', view.id));
    setReordering(false);
    fetch(model.reorderUrl, { method: 'POST', headers: { 'X-CSRFToken': model.csrfToken }, body });
  }

  return <li>
    <div className={`group relative flex items-center rounded-md ${rowClass(item.active)}`}>
      <a href={item.href} className="flex-1 min-w-0 flex items-center space-x-3 pl-4 py-2">
        <Icon spec={item.icon} className={iconClass(item.active)} />
        <span>{item.label}</span>
      </a>
      <button type="button" className={`mr-2 ${iconButton}${item.active ? '' : ` ${fine}`}`} aria-expanded={open}
        aria-label={model.labels.savedViews.replace('%(name)s', item.label)} onClick={toggle}>
        <span className={`block transition-transform duration-200${open ? '' : ' -rotate-90'}`}>
          <Icon spec={model.icons.chevron} className="w-4 h-4" />
        </span>
      </button>
      {item.pinKey && <PinMenu pinKey={item.pinKey} pinned={pins.isPinned(item.pinKey)} onToggle={pins.toggle} model={model} />}
    </div>
    {open && <ul ref={list} className="mt-1 ml-8 space-y-1">
      {views.map((view) => <li key={view.id} data-saved-view-id={view.id}
        className={`group relative flex items-center gap-2 pl-3 pr-1 rounded-md ${rowClass(view.current)}`}>
        {reordering && <span className="saved-view-drag-handle shrink-0 cursor-grab text-[var(--color-text-muted)]">
          <Icon spec={model.icons.drag} className="w-4 h-4" />
        </span>}
        <a href={view.href} aria-current={view.current ? 'page' : undefined}
          className={`flex-1 min-w-0 truncate py-1.5${reordering ? ' pointer-events-none' : ''}`}>{view.name}</a>
        {!reordering && <button type="button" className={`shrink-0 ${iconButton} ${menuFor === view.id ? 'pointer-fine:opacity-100' : fine}`}
          aria-expanded={menuFor === view.id} aria-label={model.labels.viewOptions.replace('%(name)s', view.name)}
          onClick={() => setMenuFor(menuFor === view.id ? null : view.id)}>
          <Icon spec={model.icons.ellipsis} className="w-4 h-4" />
        </button>}
        {menuFor === view.id && <div className="absolute right-0 top-full z-50 mt-1 w-36 bg-[var(--color-surface-strong)] rounded-md shadow-lg overflow-hidden border border-gray-700">
          <button type="button" className={`flex items-center gap-2 ${menuButton}`}
            onClick={() => { setMenuFor(null); setOpen(true); setReordering(true); }}>
            <Icon spec={model.icons.reorder} className="w-4 h-4" /><span>{model.labels.reorder}</span>
          </button>
          <form method="post" action={view.deleteUrl} className="m-0"
            {...{ 'hx-confirm': model.labels.confirmDelete.replace('%(name)s', view.name) }}>
            <input type="hidden" name="csrfmiddlewaretoken" value={model.csrfToken} />
            <input type="hidden" name="next" value={model.currentUrl} />
            <button type="submit" className="flex items-center gap-2 w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-[var(--color-surface-hover)] cursor-pointer">
              <Icon spec={model.icons.trash} className="w-4 h-4" /><span>{model.labels.delete}</span>
            </button>
          </form>
        </div>}
      </li>)}
      {reordering && <li><button type="button" onClick={finishReorder}
        className="flex items-center gap-2 w-full pl-3 pr-1 py-1.5 rounded-md text-sm text-left text-[var(--color-link)] hover:bg-[var(--color-hover-dim)] cursor-pointer">
        <Icon spec={model.icons.check} className="w-4 h-4 shrink-0" /><span>{model.labels.done}</span>
      </button></li>}
    </ul>}
  </li>;
}

function ListsItem({ item, pins, model, lists }) {
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem('floppy:saved-views-open:lists') === '1'; } catch { return false; }
  });
  const [menuFor, setMenuFor] = useState(null);
  const count = useRef(lists.items.length);
  // Pinning another list opens the group so the new entry is visible.
  useEffect(() => {
    if (lists.items.length > count.current) setOpen(true);
    count.current = lists.items.length;
  }, [lists.items.length]);
  const here = window.location.pathname;
  const expanded = open || lists.items.some((entry) => entry.url === here);
  const toggle = () => {
    setOpen(!expanded);
    try { localStorage.setItem('floppy:saved-views-open:lists', !expanded ? '1' : '0'); } catch { /* Works without storage. */ }
  };
  return <li>
    <div className="group relative flex items-center">
      <a href={item.href} className={`flex flex-1 min-w-0 items-center space-x-3 px-4 py-2 rounded-md ${rowClass(item.active)}`}>
        <Icon spec={item.icon} className={iconClass(item.active)} />
        <span>{item.label}</span>
      </a>
      {lists.items.length > 0 && <button type="button" aria-expanded={expanded} aria-label={model.labels.pinnedLists} onClick={toggle}
        className={`mr-1 ${iconButton}${item.active ? '' : ` ${fine}`}`}>
        <span className={`block transition-transform duration-200${expanded ? '' : ' -rotate-90'}`}>
          <Icon spec={model.icons.chevron} className="w-4 h-4" />
        </span>
      </button>}
      <PinMenu pinKey="lists" pinned={pins.isPinned('lists')} onToggle={pins.toggle} model={model} />
    </div>
    {expanded && <ul className="mt-1 ml-8 space-y-1">
      {lists.items.map((entry) => <li key={entry.id} className="group relative flex items-center rounded-md hover:bg-[var(--color-hover-dim)]">
        <a href={entry.url} className="flex-1 min-w-0 truncate pl-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]">
          <span className="truncate">{entry.name}</span>
        </a>
        <div className="relative shrink-0 mr-2">
          <button type="button" className={`p-1 rounded-md cursor-pointer text-[var(--color-text-muted)] ${menuFor === entry.id ? 'pointer-fine:opacity-100' : fine}`}
            aria-expanded={menuFor === entry.id} aria-label={model.labels.listOptions}
            onClick={() => setMenuFor(menuFor === entry.id ? null : entry.id)}>
            <Icon spec={model.icons.ellipsis} className="w-4 h-4" />
          </button>
          {menuFor === entry.id && <div className="absolute right-0 bottom-full z-50 mb-1 w-44 bg-[var(--color-surface-strong)] rounded-md shadow-lg border border-gray-700">
            <button type="button" className={menuButton} onClick={() => { lists.unpin(entry.id); setMenuFor(null); }}>{model.labels.unpin}</button>
          </div>}
        </div>
      </li>)}
    </ul>}
  </li>;
}

// Height eases open and shut like the Alpine directive it replaces.
function Reveal({ open, children }) {
  const el = useRef(null);
  const first = useRef(true);
  useLayoutEffect(() => {
    const node = el.current;
    if (first.current) { first.current = false; node.style.display = open ? '' : 'none'; return undefined; }
    const start = node.getBoundingClientRect().height;
    node.style.display = '';
    node.style.overflow = 'hidden';
    const end = open ? node.scrollHeight : 0;
    const animation = node.animate([{ height: `${start}px` }, { height: `${end}px` }], { duration: 200, easing: 'ease-in-out' });
    animation.onfinish = () => { node.style.display = open ? '' : 'none'; node.style.overflow = ''; };
    return () => animation.cancel();
  }, [open]);
  return <div ref={el}>{children}</div>;
}

export function Sidebar({ model, slots }) {
  const pinsKey = `floppy:sidebar-pins:${model.userId}`;
  const listsKey = `floppy:sidebar-lists:${model.userId}`;
  const [pinned, setPinned] = useState(() => (readJson(pinsKey, []) || []).filter((key) => model.pinKeys.includes(key)));
  const [pinnedLists, setPinnedLists] = useState(() => readJson(listsKey, []));
  const [navOpen, setNavOpen] = useState(false);
  const navList = useRef(null);
  const root = useRef(null);

  useEffect(() => {
    const onLists = () => {
      const next = readJson(listsKey, []);
      setPinnedLists((current) => {
        if (next.length > current.length && !pinned.includes('lists')) setNavOpen(true);
        return next;
      });
    };
    window.addEventListener('sidebar-lists-changed', onLists);
    return () => window.removeEventListener('sidebar-lists-changed', onLists);
  }, [listsKey, pinned]);
  // htmx does not watch the DOM: boost the links and confirm forms React adds.
  useEffect(() => { window.htmx?.process(root.current); });

  const pins = {
    isPinned: (key) => pinned.includes(key),
    toggle: (key) => {
      const next = pinned.includes(key) ? pinned.filter((entry) => entry !== key) : [...pinned, key];
      setPinned(next);
      writeJson(pinsKey, next);
    },
  };
  const lists = {
    items: pinnedLists,
    unpin: (id) => {
      const next = pinnedLists.filter((entry) => entry.id !== id);
      setPinnedLists(next);
      writeJson(listsKey, next);
      window.dispatchEvent(new Event('sidebar-lists-changed'));
    },
  };
  const hasUnpinned = model.pinKeys.some((key) => !pinned.includes(key));
  const renderItem = (item) => {
    if (item.type === 'group') return <SavedViewGroup key={item.key} item={item} pins={pins} model={model} />;
    if (item.type === 'lists') return <ListsItem key="lists" item={item} pins={pins} model={model} lists={lists} />;
    return <Link key={item.href} item={item} pins={pins} model={model} />;
  };
  const unpinnedItems = model.secondary.filter((item) => !pins.isPinned(item.pinKey));
  const pinnedItems = model.secondary.filter((item) => pins.isPinned(item.pinKey));
  const { logo, bottom } = model;

  return <div ref={root} className="contents">
    <div className="h-16 border-b border-[var(--color-border)] flex items-center px-6">
      <h1 className="flex items-center">
        <img src={logo.src} srcSet={logo.srcSet || undefined} alt="Floppy" width="158" height="48"
          className={logo.mono ? 'h-9 w-[158px] object-cover object-center' : 'h-9 w-auto'} />
      </h1>
    </div>
    <nav id="sidebar-nav" className="p-4 flex-1 min-h-0 overflow-y-auto" {...hxBoost} style={{ WebkitOverflowScrolling: 'touch' }}>
      <ul className="space-y-1">{model.primary.map((item) => renderItem({ ...item, pinKey: null }))}</ul>
    </nav>
    {(navOpen || pinned.length > 0) && <nav className="border-t border-[var(--color-border)] px-4 py-4" {...hxBoost}>
      <div ref={navList} className="overflow-y-auto max-h-[40dvh]" style={{ WebkitOverflowScrolling: 'touch' }}>
        <Reveal open={navOpen}><ul className="space-y-1">{unpinnedItems.map(renderItem)}</ul></Reveal>
        <ul className="space-y-1">{pinnedItems.map(renderItem)}</ul>
      </div>
    </nav>}
    <div data-sidebar-slot="onboarding" ref={(node) => { if (node && slots.onboarding && node.firstChild !== slots.onboarding) node.replaceChildren(slots.onboarding); }} className="contents" />
    <div className="p-4 border-t border-[var(--color-border)] mt-auto">
      <div className="space-y-2">
        {hasUnpinned && <div>
          <button type="button" aria-expanded={navOpen}
            className="flex w-full items-center gap-3 px-4 py-2 rounded-md text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-hover-dim)] cursor-pointer"
            onClick={() => {
              setNavOpen(!navOpen);
              if (!navOpen) requestAnimationFrame(() => { if (navList.current) navList.current.scrollTop = navList.current.scrollHeight; });
            }}>
            <span className={`transition-transform duration-200${navOpen ? '' : ' rotate-180'}`}>
              <Icon spec={model.icons.chevron} className="w-5 h-5" />
            </span>
            <span>{model.labels.explore}</span>
          </button>
        </div>}
        <a href={bottom.appearance.href} {...hxBoost}
          className={`lg:hidden flex items-center space-x-3 px-4 py-2 rounded-md ${rowClass(bottom.appearance.active)}`}>
          <Icon spec={bottom.appearance.icon} className="w-5 h-5" /><span>{bottom.appearance.label}</span>
        </a>
        <a href={bottom.settings.href} {...hxBoost}
          className={`flex items-center space-x-3 px-4 py-2 rounded-md ${rowClass(bottom.settings.active)}`}>
          <Icon spec={bottom.settings.icon} className={iconClass(bottom.settings.active)} /><span>{bottom.settings.label}</span>
        </a>
        <form method="post" action={bottom.logoutAction} className="w-full">
          <input type="hidden" name="csrfmiddlewaretoken" value={model.csrfToken} />
          <button type="submit"
            className="w-full flex items-center space-x-3 px-4 py-2 rounded-md text-[var(--color-text-muted)] hover:bg-[var(--color-hover-dim)] hover:text-[var(--color-text)] transition-colors duration-200 text-sm cursor-pointer">
            <Icon spec={bottom.logoutIcon} className="w-5 h-5" /><span>{model.labels.logout}</span>
          </button>
        </form>
      </div>
    </div>
  </div>;
}
