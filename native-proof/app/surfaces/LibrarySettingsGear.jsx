import React from 'react';
import { ActionMenu } from '../../../frontend/ui/controls/Menu';
import { Icon } from '../../../frontend/ui/Icon';
import { actionIcons } from '../../../frontend/ui/actionIcons';

// The media list settings gear, as the web header shows it.
export default function LibrarySettingsGear({ items, palette }) {
  return <ActionMenu label="View settings" palette={palette} testID="library-settings"
    icon={<Icon spec={actionIcons.settings} size={18} color={palette.textSecondary} />}
    items={items} />;
}
