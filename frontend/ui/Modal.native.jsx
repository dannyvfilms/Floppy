import React, { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Modal as NativeModal, Pressable, StyleSheet, View } from 'react-native';

const RailModalContext = createContext(null);
const RailModalActiveContext = createContext(null);
const RailModalMetaContext = createContext(null);

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
  const value = useMemo(() => ({ enabled, register, unregister }), [enabled, register, unregister]);
  // The shell toolbar needs only who is open and how to close it. Keeping that apart from the
  // dialog's content stops every content render from re-rendering the shell, which re-registers
  // the toolbar and re-renders the page again (a "Maximum update depth" loop).
  const meta = useMemo(() => active ? { id: active.id, onRequestClose: active.onRequestClose } : null,
    [active?.id, active?.onRequestClose]);
  return <RailModalContext.Provider value={value}>
    <RailModalMetaContext.Provider value={meta}>
      <RailModalActiveContext.Provider value={active}>{children}</RailModalActiveContext.Provider>
    </RailModalMetaContext.Provider>
  </RailModalContext.Provider>;
}

export function useRailModal() {
  const rail = useContext(RailModalContext);
  const active = useContext(RailModalMetaContext);
  return rail ? { ...rail, active } : null;
}

export function Modal({ visible = true, children, onRequestClose, onShow, ...props }) {
  const rail = useContext(RailModalContext);
  const id = useId();
  const enabled = rail?.enabled;
  const register = rail?.register;
  const unregister = rail?.unregister;
  // A stable close, so a new inline callback on every render does not look like a change.
  const closeRef = useRef(onRequestClose);
  closeRef.current = onRequestClose;
  const stableClose = useCallback(() => closeRef.current?.(), []);
  useLayoutEffect(() => {
    if (!enabled || !visible) return undefined;
    register(id, { children, onRequestClose: stableClose });
  }, [enabled, visible, children, stableClose, id, register]);
  useLayoutEffect(() => () => { if (enabled && visible) unregister(id); }, [enabled, visible, id, unregister]);
  useEffect(() => { if (enabled && visible) onShow?.(); }, [enabled, visible, onShow]);
  return enabled ? null : <NativeModal {...props} visible={visible} onRequestClose={onRequestClose} onShow={onShow}>{children}</NativeModal>;
}

export function ModalCloseButton(props) {
  const rail = useContext(RailModalContext);
  return rail?.enabled ? null : <Pressable {...props} />;
}

export function RailModalHost() {
  const active = useContext(RailModalActiveContext);
  return active ? <View key={active.id} accessibilityViewIsModal role="dialog" style={styles.overlay}>
    {active.children}
  </View> : null;
}

const styles = StyleSheet.create({ overlay: { ...StyleSheet.absoluteFill, zIndex: 100, elevation: 100 } });
