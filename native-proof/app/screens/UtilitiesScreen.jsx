import React, { useState } from 'react';
import { Text } from 'react-native';
import { UtilitiesView } from '../../../frontend/pages/UtilitiesView';
import { Button } from '../../../frontend/ui/Button';
import { Screen } from '../components/Screen';
import { getActiveAuthSession } from '../data/authSession';
import { copyText } from '../data/fileFlows';
import { integrationButtonPalette, integrationPalette } from './integrationPalette';
import { palette } from '../theme';

export const surface = {
  id: 'UTILITIES',
  status: 'ported',
  title: 'Utilities: copy the server address',
  where: 'Settings, Utilities (web: clipboard, install and static cache cards)',
  note: 'Shows the connected server address with a copy action through the system share sheet. PWA install and the service-worker cache are web-only by nature (browser APIs) and are not shown in the app.',
};

export default function UtilitiesScreen({ onBack, navigate }) {
  const [session] = useState(() => getActiveAuthSession());
  const colors = integrationPalette();
  const buttons = integrationButtonPalette();
  if (!session?.serverUrl) {
    return <Screen title="Utilities" onBack={onBack}>
      <Text accessibilityRole="alert" style={{ color: palette.danger }}>Sign in to your Floppy server to see its address.</Text>
      <Button label="Sign In" tone="surface" palette={buttons} onPress={() => navigate?.('Auth')} />
    </Screen>;
  }
  return <Screen title="Utilities" onBack={onBack}>
    <UtilitiesView
      labels={{
        title: 'Server address',
        copy: 'Copy the address of the Floppy server this app is connected to.',
        copyHeading: 'Copy controls',
      }}
      copyFields={[{ id: 'server-url', label: 'Server URL', value: session.serverUrl }]}
      onCopy={text => copyText(text)}
      palette={colors} buttonPalette={buttons} />
  </Screen>;
}
