import React, { useEffect, useState } from 'react';

const defaultLabels = {
  copy: 'Copy',
  copied: 'Copied',
  traceback: 'Traceback',
  reportNote: 'Copy this block when opening a ticket so the traceback and request details are preserved.',
};

/** Browser traceback panel. It reproduces the release server markup: a surface
 * card with the copy control in the header and a fixed-height, horizontally
 * scrolling textarea that holds the safe diagnostic report. */
export function ErrorReportPanel({
  report = '',
  title = defaultLabels.traceback,
  note = defaultLabels.reportNote,
  copyLabel = defaultLabels.copy,
  copiedLabel = defaultLabels.copied,
  copyIcon,
  copiedIcon,
  onCopy,
  palette,
  testID,
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 3000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    if (!onCopy) return;
    const result = await onCopy(report);
    if (result !== false) setCopied(true);
  }

  return <div data-testid={testID}
    style={{
      width: '100%',
      boxSizing: 'border-box',
      marginBottom: 16,
      padding: 16,
      textAlign: 'left',
      borderRadius: 12,
      backgroundColor: palette.surface,
      color: palette.text,
    }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
      <h3 style={{ margin: 0, fontSize: 16, lineHeight: '24px', fontWeight: 500, color: palette.textSecondary }}>
        {title}
      </h3>
      {onCopy ? <button type="button" onClick={copy}
        aria-label={copied ? copiedLabel : copyLabel}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 12px',
          border: 0,
          borderRadius: 12,
          cursor: 'pointer',
          font: 'inherit',
          fontSize: 14,
          lineHeight: '20px',
          backgroundColor: palette.surfaceStrong,
          color: palette.textSecondary,
        }}>
        <span style={{ display: 'inline-flex', width: 20, height: 20, color: copied ? '#34d399' : palette.textMuted }}>
          {copied ? copiedIcon : copyIcon}
        </span>
        <span>{copyLabel}</span>
      </button> : null}
    </div>
    <p style={{ margin: '0 0 8px', fontSize: 12, lineHeight: '16px', color: palette.textMuted }}>
      {note}
    </p>
    <textarea readOnly value={report} spellCheck={false} wrap="off"
      onClick={event => event.currentTarget.select()}
      style={{
        display: 'inline-block',
        width: '100%',
        height: '16rem',
        boxSizing: 'border-box',
        margin: 0,
        padding: 8,
        resize: 'vertical',
        borderRadius: 12,
        border: `1px solid ${palette.surfaceStrong}`,
        backgroundColor: palette.background,
        color: palette.textSecondary,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontSize: 12,
        lineHeight: '16px',
        whiteSpace: 'pre',
        overflow: 'auto',
      }} />
  </div>;
}
