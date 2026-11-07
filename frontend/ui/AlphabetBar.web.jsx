import React from 'react';

// Browser presentation for the alphabet rail. The shared component owns the
// native layout; this adapter keeps real anchors, hrefs and the server rail CSS.
export function AlphabetBar({ options, label, palette = {}, onNavigate }) {
  return <nav aria-label={label} style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
    {options.map(option => <a key={option.value} href={option.href}
      data-alphabet-initial={option.value === 'other' ? 'other' : undefined}
      data-alphabet-caption={option.caption || undefined}
      aria-current={option.selected ? 'true' : undefined}
      aria-label={option.accessibilityLabel}
      onClick={event => onNavigate(event, option)}
      style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'pointer', textDecoration: 'none',
        color: option.selected ? palette.selectedText : palette.mutedText,
        fontFamily: palette.fontFamily,
        fontSize: option.caption ? palette.captionSize : palette.letterSize,
        lineHeight: palette.letterSize, fontWeight: option.selected ? '600' : '400', textAlign: 'center' }}>
      <span>{option.label}</span>
    </a>)}
  </nav>;
}

export function AlphabetEmpty({ title, clearLabel, option, onNavigate }) {
  return <div style={{ alignItems: 'center', display: 'flex', flexDirection: 'column', gap: 16, padding: 48 }}>
    <h3 style={{ margin: 0, fontSize: 20, lineHeight: '24px', fontWeight: 600 }}>{title}</h3>
    <a href={option.href} onClick={event => onNavigate(event, option)}
      style={{ padding: '4px 8px', border: '1px solid var(--color-border)', borderRadius: 4,
        background: 'var(--color-surface)', color: 'var(--color-text)', fontSize: 12,
        lineHeight: '16px', textDecoration: 'none' }}>{clearLabel}</a>
  </div>;
}
