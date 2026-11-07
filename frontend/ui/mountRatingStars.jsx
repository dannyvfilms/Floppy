import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { RatingStarIcon } from './RatingStarIcon.web';
import { RatingStars } from './RatingStars';

const palette = {
  lit: '#facc15', unlit: '#4b5563', muted: 'var(--color-text-muted)',
  focusStyle: { outlineStyle: 'solid', outlineWidth: 1, outlineColor: 'var(--color-accent)' },
};
const star = (lit, size = 20) => RatingStarIcon(lit, size);

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
