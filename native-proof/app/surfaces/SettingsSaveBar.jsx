import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { FormSaveBar } from '../../../frontend/ui/FormSaveBar';

const SaveBarContext = createContext(null);

// The settings screen owns the viewport overlay. Editors keep their existing
// save state and callbacks; their scroll content does not own the dock geometry.
export function SettingsSaveBarHost({ children }) {
  const [bar, setBar] = useState(null);
  return <SaveBarContext.Provider value={setBar}>
    <View style={styles.root}>
      {children}
      {bar ? <View style={styles.dock}>{bar}</View> : null}
    </View>
  </SaveBarContext.Provider>;
}

export default function SettingsSaveBar(props) {
  const setBar = useContext(SaveBarContext);
  const latest = useRef(props);
  latest.current = props;
  // Callback identity changes must not cause an overlay/render feedback loop.
  // The ref supplies the current action; the serializable presentation drives
  // updates (dirty, saving, errors, translated copy and theme colors).
  const signature = JSON.stringify(props);
  useEffect(() => {
    if (!setBar) return undefined;
    setBar(<FormSaveBar {...latest.current} onSave={() => latest.current.onSave?.()} />);
    return () => setBar(null);
  }, [setBar, signature]);
  return setBar ? null : <FormSaveBar {...props} />;
}

const styles = StyleSheet.create({
  root: { flex: 1, minHeight: 0 },
  dock: { position: 'absolute', left: 16, right: 16, bottom: 16, zIndex: 20 },
});
