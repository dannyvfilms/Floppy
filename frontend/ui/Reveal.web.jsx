import React from 'react';

// Web moves the panel inside a fixed clip so the browser can composite the
// animation without recalculating layout on every frame. Native uses its own
// measured-height animation because it does not use browser CSS transitions.
// The clip carries data-open too: sidebar.css hides it while closed so the
// load-time measurement records no layout shift (web-only; see sidebar.css).
export function Reveal({ open, children, duration = 200 }) {
  return <div className="sidebar-reveal-clip" data-open={open ? 'true' : 'false'} inert={!open}
    style={{ overflow: 'hidden', pointerEvents: open ? 'auto' : 'none', '--sidebar-reveal-duration': `${duration}ms` }}>
    <div className="sidebar-reveal" data-open={open ? 'true' : 'false'}>
      {children}
    </div>
  </div>;
}
