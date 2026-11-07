import React from 'react';
import { Modal as SharedModal, ModalCloseButton as SharedCloseButton } from './Modal.jsx';
export function Modal(props) { return <SharedModal {...props} />; }
export function ModalCloseButton(props) { return <SharedCloseButton {...props} />; }
export function RailModalProvider({ children }) { return <React.Fragment>{children}</React.Fragment>; }
export function RailModalHost() { return <React.Fragment />; }
export function useRailModal() { return null; }
