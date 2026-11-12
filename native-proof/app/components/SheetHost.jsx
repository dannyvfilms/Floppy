import React from 'react';
import { BottomSheet, RNHostView } from '@expo/ui';

export function SheetContainer(props) { return <BottomSheet {...props} />; }
export function SheetHost(props) { return <RNHostView {...props} />; }
