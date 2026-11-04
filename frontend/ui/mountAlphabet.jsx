import React from 'react';
import { mountRoot } from '../settings/root';
import { AlphabetBar, AlphabetEmpty } from './AlphabetBar';

export function mountAlphabet(host, props) {
  const palette = {
    badgeBorder: 'var(--color-border)', badgeBackground: 'var(--color-surface)',
    badgeText: 'var(--color-text)', badgeHover: 'var(--color-surface-hover)', fontFamily: 'inherit',
    selectedText: 'var(--color-accent)', mutedText: 'var(--color-text-muted)',
    letterSize: 'var(--alphabet-letter-size)', captionSize: 'var(--alphabet-caption-size)',
    focusStyle: { outlineStyle: 'solid', outlineWidth: 1, outlineColor: 'var(--color-accent)', outlineOffset: -1 },
    interactiveStyle: { cursor: 'pointer', textDecorationLine: 'none', textAlign: 'center' },
  };
  function onNavigate(event, option) {
    const nativeEvent = event.nativeEvent || event;
    if (nativeEvent.metaKey || nativeEvent.ctrlKey || nativeEvent.shiftKey || nativeEvent.altKey) return;
    event.preventDefault();
    const url = new URL(option.href, window.location.href);
    const form = document.getElementById(props.formId);
    if (form) {
      for (const name of new Set([...form.elements].map(field => field.name).filter(Boolean))) url.searchParams.delete(name);
      for (const [name, value] of new FormData(form)) {
        if (typeof value === 'string' && value.trim()) url.searchParams.append(name, value.trim());
      }
    }
    url.searchParams.delete('page'); url.searchParams.delete('ug_page'); url.searchParams.delete('initial');
    if (option.value) url.searchParams.set('initial', option.value);
    window.location.assign(url.href);
  }
  if (props.mode === 'empty') return mountRoot(host,
    <AlphabetEmpty title={props.emptyTitle} clearLabel={props.clearLabel} option={props.options[0]} palette={palette} onNavigate={onNavigate} />);

  let results, frame = 0, disposed = false;
  const textMetrics = document.createElement('canvas').getContext('2d');
  const observer = new ResizeObserver(() => schedulePosition());
  function position() {
    const next = document.querySelector(props.resultsSelector);
    if (next !== results) {
      if (results) observer.unobserve(results);
      results = next;
      if (results) observer.observe(results);
    }
    if (!results) return;
    const poster = results.querySelector('img')?.getBoundingClientRect();
    const anchorTop = poster?.width && poster?.height ? poster.top : results.getBoundingClientRect().top;
    const top = `${Math.max(96, Math.ceil(anchorTop))}px`;
    if (host.style.getPropertyValue('--alphabet-top') !== top) host.style.setProperty('--alphabet-top', top);

    // Full-width punctuation can have asymmetric side bearings. Center its ink,
    // using the rendered font, rather than centering the empty advance space.
    const symbol = host.querySelector('[data-alphabet-initial="other"] > *');
    if (symbol && textMetrics) {
      const style = getComputedStyle(symbol);
      textMetrics.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const metrics = textMetrics.measureText(symbol.textContent);
      const box = symbol.getBoundingClientRect(), link = symbol.parentElement.getBoundingClientRect();
      const previous = parseFloat(host.style.getPropertyValue('--alphabet-symbol-offset')) || 0;
      const inkCenter = box.left - previous + (box.width - metrics.width) / 2 + (metrics.actualBoundingBoxRight - metrics.actualBoundingBoxLeft) / 2;
      const offset = `${(link.left + link.width / 2 - inkCenter).toFixed(2)}px`;
      if (host.style.getPropertyValue('--alphabet-symbol-offset') !== offset) host.style.setProperty('--alphabet-symbol-offset', offset);
    }
  }
  function schedulePosition() {
    if (!disposed && !frame) frame = requestAnimationFrame(() => { frame = 0; position(); });
  }
  position();
  let dispose;
  try {
    dispose = mountRoot(host, <AlphabetBar {...props} palette={palette} onNavigate={onNavigate} />);
  } catch (error) {
    observer.disconnect();
    throw error;
  }
  position();
  observer.observe(document.body);
  window.addEventListener('resize', schedulePosition);
  document.addEventListener('scroll', schedulePosition, { capture: true, passive: true });
  document.addEventListener('htmx:afterSettle', schedulePosition);
  document.addEventListener('animationend', schedulePosition);
  document.addEventListener('transitionend', schedulePosition);
  document.fonts?.ready.then(schedulePosition);
  document.fonts?.addEventListener('loadingdone', schedulePosition);
  return () => {
    disposed = true;
    cancelAnimationFrame(frame);
    observer.disconnect();
    window.removeEventListener('resize', schedulePosition);
    document.removeEventListener('scroll', schedulePosition, true);
    document.removeEventListener('htmx:afterSettle', schedulePosition);
    document.removeEventListener('animationend', schedulePosition);
    document.removeEventListener('transitionend', schedulePosition);
    document.fonts?.removeEventListener('loadingdone', schedulePosition);
    dispose();
  };
}
