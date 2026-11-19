import React from 'react';
import { View } from 'react-native';

// Non-iOS surfaces keep the existing shared shell.
export default function NativeShell({ children }) { return <View style={{ flex: 1 }}>{children}</View>; }
