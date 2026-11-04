import React, { cloneElement } from 'react';
import { Chip as SharedChip } from './Chip.jsx';
import { webPalette } from './webPalette';

/** Browser adapter: attaches anchor navigation and new-tab attributes to the
 * shared chip's link mode, keeping one visual and focusable element.
 */
export function Chip({ href, hrefAttrs, onPress, accessibilityLabel, ...props }) {
  const chip = <SharedChip {...props} accessibilityLabel={accessibilityLabel}
    onPress={onPress} link={Boolean(href)} palette={webPalette} />;
  return href ? cloneElement(chip, { href, hrefAttrs }) : chip;
}
