import React from 'react';
import { View } from 'react-native';
import { SettingsCard } from '../settings/SettingsCard';
import { CopyBlock } from '../ui/CopyBlock';

const defaultLabels = {
  copy: 'Copy',
  copied: 'Copied',
  traceback: 'Traceback',
  reportNote: 'Copy this block when opening a ticket so the traceback and request details are preserved.',
};

function cardPalette(palette) {
  return {
    text: palette.text,
    border: palette.border,
    background: palette.surface,
    badgeBorder: palette.border,
    badgeBackground: palette.surfaceStrong,
    badgeText: palette.textSecondary,
    badgeHover: palette.surfaceMuted,
    focusStyle: palette.focusStyle,
  };
}

/** Native traceback panel. The web build uses ErrorReportPanel.web.jsx, which
 * keeps the release page's fixed-height textarea and header copy button. */
export function ErrorReportPanel({
  report,
  title = defaultLabels.traceback,
  note = defaultLabels.reportNote,
  copyLabel = defaultLabels.copy,
  copiedLabel = defaultLabels.copied,
  onCopy,
  palette,
  testID,
}) {
  return <View>
    <SettingsCard title={title} badge="Diagnostic" palette={cardPalette(palette)}>
      <CopyBlock text={report} note={note} copyLabel={copyLabel} copiedLabel={copiedLabel}
        onCopy={onCopy} palette={palette} testID={testID} />
    </SettingsCard>
  </View>;
}
