import React, { cloneElement } from 'react';
import { SettingsNavLink as SharedSettingsNavLink } from './SettingsNavLink.jsx';

// Browser row adapter: the server navigation model supplies each URL, so the
// shared row becomes a real anchor inside the boosted settings navigation. The
// anchor keeps aria-current, focus and hover state from the universal row.
export function SettingsNavLink({ item, onPress, ...props }) {
  const link = <SharedSettingsNavLink item={item} {...props}
    onPress={item.url ? undefined : onPress} />;
  return item.url ? cloneElement(link, { href: item.url }) : link;
}
