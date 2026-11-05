import React from 'react';
import { mountRoot } from '../settings/root';
import { DetailChildrenTheme } from './DetailChildrenTheme.web';

export function mountDetailChildren(host, props) {
  const mount = host.querySelector('[data-detail-children-react]');
  if (!mount) return () => {};
  return mountRoot(mount, <DetailChildrenTheme host={host} props={props} />);
}
