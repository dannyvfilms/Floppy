import React from 'react';
import { Modal as NativeModal, Pressable } from 'react-native';

export function Modal(props) { return <NativeModal {...props} />; }
export function ModalCloseButton(props) { return <Pressable {...props} />; }
export function RailModalProvider({ children }) { return <React.Fragment>{children}</React.Fragment>; }
export function RailModalHost() { return <React.Fragment />; }
export function useRailModal() { return null; }
