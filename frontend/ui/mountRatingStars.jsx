import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { RatingStars } from './RatingStars';

const palette = {
  lit: '#facc15', unlit: '#4b5563', muted: 'var(--color-text-muted)',
  focusStyle: { outlineStyle: 'solid', outlineWidth: 1, outlineColor: 'var(--color-accent)' },
};
const star = () => <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
  fill="currentColor" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
</svg>;

// The Alpine popup owns the current score on its wrapper (`data-rating`); the
// write goes through htmx so the server's out-of-band chip and card swaps apply.
const read = (wrapper) => {
  const value = parseFloat(wrapper?.dataset.rating);
  return Number.isFinite(value) ? value : null;
};

function Adapter({ host, props }) {
  const wrapper = host.parentElement;
  const [value, setValue] = useState(() => read(wrapper));
  useEffect(() => {
    const observer = new MutationObserver(() => setValue(read(wrapper)));
    observer.observe(wrapper, { attributes: true, attributeFilter: ['data-rating'] });
    return () => observer.disconnect();
  }, [wrapper]);
  function onSelect(score) {
    host.dispatchEvent(new CustomEvent('rating-select', { bubbles: true, detail: { value: score } }));
    window.htmx?.ajax('POST', props.postUrl, {
      source: host, swap: 'none',
      headers: { 'X-CSRFToken': props.csrfToken },
      values: { score: score ?? value, toggle: true },
    });
  }
  return <RatingStars scaleMax={props.scaleMax} value={value} label={props.label}
    renderStar={star} onSelect={onSelect} palette={palette} />;
}

export function mountRatingStars(host, props) {
  return mountRoot(host, <Adapter host={host} props={props} />);
}
