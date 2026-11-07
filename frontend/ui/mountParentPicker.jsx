import React from 'react';
import { mountRoot } from '../settings/root';
import { ParentPicker } from './ParentPicker.web.jsx';

export function mountParentPicker(host, props) {
  return mountRoot(host, <ParentPicker props={props} />);
}
