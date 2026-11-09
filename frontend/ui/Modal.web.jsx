// Web keyboard adapter; native platforms retain the platform Modal.
import React, { useEffect } from 'react';
import { Modal as NativeModal, Pressable } from 'react-native';
export function Modal({ visible, onRequestClose, ...props }) {
  useEffect(() => {
    if (!visible || typeof onRequestClose !== 'function') return undefined;
    const handler = event => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      event.preventDefault();
      event.stopPropagation();
      onRequestClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [visible, onRequestClose]);
  return <NativeModal visible={visible} onRequestClose={onRequestClose} {...props} />;
}
export function ModalCloseButton(props) { return <Pressable {...props} />; }
export function RailModalProvider({ children }) { return <React.Fragment>{children}</React.Fragment>; }
export function RailModalHost() { return <React.Fragment />; }
export function useRailModal() { return null; }
