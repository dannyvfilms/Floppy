import React from 'react';
import { mountRoot } from './root';

// Presentation only: the server supplies translated sections, lines and tones.
export function BackupStatus({ sections }) {
  return <>
    {sections.map(section => <div key={section.id} className="ui-backup-status" data-backup-section={section.id}>
      {section.intro}{section.path && <> <code>{section.path}</code></>}
      {section.lines.map((line, index) => <div key={index} className={`ui-backup-line ui-backup-${line.tone}`}>{line.text}</div>)}
    </div>)}
  </>;
}

export function mountBackupStatus(host, props) {
  return mountRoot(host, <BackupStatus sections={props} />);
}
