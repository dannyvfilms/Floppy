import React from 'react';
import { mountRoot } from '../settings/root';
import { Sidebar } from './Sidebar';

// The onboarding banner stays server-rendered; lift it out before React takes over.
export function mountSidebar(host, props) {
  const slots = { onboarding: host.querySelector('[data-sidebar-slot="onboarding"]') };
  return mountRoot(host, <Sidebar model={props} slots={slots} />);
}
