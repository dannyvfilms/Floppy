import React from 'react';
import { Rail } from '../../../frontend/ui/Rail';

// Native mounts only the cards near the visible window so artwork loads in order;
// the web leaves every card mounted because its images already load lazily. Touch
// devices swipe a row, so native also drops the mouse paging arrows.
export default function WindowedRail(props) {
  return <Rail windowCards showArrows={false} {...props} />;
}
