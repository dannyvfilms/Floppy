import React from 'react';
import { mountRoot } from '../settings/root';
import { Badge } from './controls';

export function mountBadge(host, props) {
  return mountRoot(host, <Badge {...props} />);
}
