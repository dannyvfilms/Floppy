import React, { useState } from 'react';
import { Button, Text, View } from 'react-native';
import NativeShell from '../surfaces/NativeShell';
import { Dialog } from '../../../frontend/ui/controls/Dialog';
import { palette } from '../theme';
export default function RailPreview() {
  const [open, setOpen] = useState(false);
  const [modal, setModal] = useState(false);
  return <NativeShell open={open} onToggle={() => setOpen(v => !v)} palette={{...palette, sidebar:palette.background}}
    canGoBack onBack={() => setOpen(false)} sidebar={<Text>Sidebar</Text>} search={<Text>Search</Text>}>
    <View style={{flex:1}}><Button title="Open test dialog" onPress={() => setModal(true)} />
      <Dialog open={modal} title="Rail close test" onClose={() => setModal(false)}><Text>Dismiss this dialog using the side rail.</Text></Dialog>
    </View>
  </NativeShell>;
}
