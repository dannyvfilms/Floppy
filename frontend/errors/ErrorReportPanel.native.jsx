import React from 'react';
import { View } from 'react-native';
import { ErrorReportPanel as SharedErrorReportPanel } from './ErrorReportPanel.jsx';

// Native placement for the shared traceback panel.
export function ErrorReportPanel(props) {
  return <View><SharedErrorReportPanel {...props} /></View>;
}
