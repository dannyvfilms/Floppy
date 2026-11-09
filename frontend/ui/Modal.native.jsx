import React, { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useState } from 'react';
import { Modal as NativeModal, Pressable, StyleSheet, View } from 'react-native';

const RailModalContext = createContext(null);

// The Duo rail belongs to the screen controller. Keep dialogs in its canvas
// rather than presenting a second controller that takes ownership of the rail.
export function RailModalProvider({ enabled, children }) {
  const [entries, setEntries] = useState([]);
  const register = useCallback((id, entry) => setEntries(current => {
    const index = current.findIndex(item => item.id === id);
    if (index < 0) return [...current, { id, ...entry }];
    return current.map((item, position) => position === index ? { id, ...entry } : item);
  }), []);
  const unregister = useCallback(id => setEntries(current => current.filter(item => item.id !== id)), []);
  const active = enabled ? entries[entries.length - 1] : null;
  const value = useMemo(() => ({ enabled, register, unregister, active }), [enabled, register, unregister, active]);
  return <RailModalContext.Provider value={value}>{children}</RailModalContext.Provider>;
}

export function useRailModal() { return useContext(RailModalContext); }

export function Modal({ visible = true, children, onRequestClose, onShow, ...props }) {
  const rail = useRailModal();
  const id = useId();
  const enabled = rail?.enabled;
  const register = rail?.register;
  const unregister = rail?.unregister;
  useLayoutEffect(() => {
    if (!enabled || !visible) return undefined;
    register(id, { children, onRequestClose });
  }, [enabled, visible, children, onRequestClose, id, register]);
  useLayoutEffect(() => () => { if (enabled && visible) unregister(id); }, [enabled, visible, id, unregister]);
  useEffect(() => { if (enabled && visible) onShow?.(); }, [enabled, visible, onShow]);
  return enabled ? null : <NativeModal {...props} visible={visible} onRequestClose={onRequestClose} onShow={onShow}>{children}</NativeModal>;
}

export function ModalCloseButton(props) {
  const rail = useRailModal();
  return rail?.enabled ? null : <Pressable {...props} />;
}

export function RailModalHost() {
  const rail = useRailModal();
  return rail?.active ? <View key={rail.active.id} accessibilityViewIsModal role="dialog" style={styles.overlay}>
    {rail.active.children}
  </View> : null;
}

const styles = StyleSheet.create({ overlay: { ...StyleSheet.absoluteFill, zIndex: 100, elevation: 100 } });
