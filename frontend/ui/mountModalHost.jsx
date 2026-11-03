import React from 'react';
import { mountRoot } from '../settings/root';
import { ModalHost } from './ModalHost';

export function mountModalHost(host) {
  return mountRoot(host, <ModalHost />);
}
