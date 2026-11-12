import React from 'react';
import { Rail } from '../../../frontend/ui/Rail';

// Native mounts only the cards near the visible window so artwork loads in order;
// the web leaves every card mounted because its images already load lazily.
export default function WindowedRail(props) {
  return <Rail windowCards {...props} />;
}
