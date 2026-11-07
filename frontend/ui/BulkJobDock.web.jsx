import React from 'react';

export function BulkJobDock({ children, label = 'Bulk jobs' }) {
  return <div className="ui-dock" role="group" aria-live="polite" aria-label={label}>
    {children}
  </div>;
}
