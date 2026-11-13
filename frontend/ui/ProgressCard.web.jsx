import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const defaultLabels = {
  yourProgress: 'Your Progress',
  caughtUp: 'Caught Up',
  aboutProgress: 'About your progress',
  progressTip: 'Your progress is how much of the show you have watched at least once. While you rewatch, a glowing line shows how far along the rewatch is.',
  openBreakdown: 'Open the season and episode breakdown',
};

function clamp(percent) {
  return Math.max(0, Math.min(100, Number(percent) || 0));
}

/**
 * Browser implementation of the shared “Your Progress” card contract.
 *
 * The detail chip row defines the card geometry in CSS, so this platform
 * implementation keeps the established class names while the Django adapter
 * owns transport and the dialog. The shared React Native card remains the
 * native implementation.
 */
export function ProgressCard({ model, labels, onOpen }) {
  const text = { ...defaultLabels, ...labels };
  const [infoOpen, setInfoOpen] = useState(false);
  const [tipStyle, setTipStyle] = useState(null);
  const triggerRef = useRef(null);
  const percent = clamp(model?.percent);
  const rewatch = model?.rewatch || null;
  const subtitle = rewatch ? rewatch.label : model?.caughtUp ? text.caughtUp : null;
  const glow = rewatch && clamp(rewatch.width) > 0;

  useEffect(() => {
    if (!infoOpen) return undefined;
    const dismiss = () => setInfoOpen(false);
    const escape = event => { if (event.key === 'Escape') dismiss(); };
    const outside = event => {
      if (!triggerRef.current?.contains(event.target)) dismiss();
    };
    window.addEventListener('scroll', dismiss, true);
    window.addEventListener('keydown', escape);
    document.addEventListener('pointerdown', outside);
    return () => {
      window.removeEventListener('scroll', dismiss, true);
      window.removeEventListener('keydown', escape);
      document.removeEventListener('pointerdown', outside);
    };
  }, [infoOpen]);

  function place() {
    const node = triggerRef.current;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const width = Math.min(256, window.innerWidth - 32);
    const left = Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16));
    setTipStyle({ top: rect.top - 8, left, width, transform: 'translateY(-100%)' });
    setInfoOpen(true);
  }

  const tooltip = infoOpen && tipStyle && typeof document !== 'undefined'
    ? createPortal(<div role="tooltip"
      className="fixed z-50 rounded-lg border border-[var(--color-surface-border)] bg-[var(--color-surface-strong)] p-3 text-xs text-[var(--color-text)] shadow-lg"
      style={tipStyle}>{text.progressTip}</div>, document.body)
    : null;

  return <div className="relative">
    <button type="button"
      className="detail-progress-card w-full cursor-pointer text-left"
      aria-haspopup="dialog"
      aria-label={text.yourProgress}
      aria-description={subtitle || undefined}
      onClick={() => onOpen?.()}>
      <span className="detail-progress-card__title">{text.yourProgress}
        {subtitle ? <span className="detail-progress-card__sub">{subtitle}</span> : null}</span>
      <span className="detail-progress-card__bar"
        role="progressbar"
        aria-label={text.yourProgress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}>
        <span style={{ width: `${percent}%` }}></span>
        {glow ? <span className="progress-glow"
          aria-hidden="true"
          style={{ left: `${clamp(rewatch.offset)}%`, width: `${clamp(rewatch.width)}%` }}></span> : null}
      </span>
      {rewatch ? <span className="sr-only"
        role="progressbar"
        aria-label={rewatch.label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={clamp(rewatch.percent)}></span> : null}
      <strong className="detail-progress-card__value">{percent}%</strong>
    </button>
    <div className="absolute right-3 top-3 z-10">
      <button type="button"
        ref={triggerRef}
        className="inline-flex cursor-pointer items-center text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)]"
        aria-label={text.aboutProgress}
        aria-expanded={infoOpen}
        onPointerEnter={event => { if (event.pointerType === 'mouse') place(); }}
        onPointerLeave={event => { if (event.pointerType === 'mouse') setInfoOpen(false); }}
        onClick={event => {
          if (event.pointerType === 'mouse' || !infoOpen) place();
          else setInfoOpen(false);
        }}>
        <svg xmlns="http://www.w3.org/2000/svg"
          width="1em"
          height="1em"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-3.5 w-3.5"
          aria-hidden="true"
          focusable="false">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4" />
          <path d="M12 8h.01" />
        </svg>
      </button>
      {tooltip}
    </div>
  </div>;
}
