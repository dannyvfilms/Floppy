import React from 'react';
import { Text, View } from 'react-native';
import { SheetCloseButton } from './SheetCloseButton';
import { SheetContainer, SheetHost } from './SheetHost';

// Android's native sheet offers half and full states rather than arbitrary detents.
export function AdaptivePresentationSheet({ children, title, onClose, titleColor = '#fff', snapPoints = ['half', 'full'], ...props }) {
  return <SheetContainer snapPoints={snapPoints} showDragIndicator contentPadding={0} {...props}>
    <SheetHost><View style={{ flex: 1 }}>
      {title ? <View style={{ height: 68, paddingHorizontal: 16, justifyContent: 'center', alignItems: 'flex-start' }}>
        <Text accessibilityRole="header" numberOfLines={1} style={{ color: titleColor, fontSize: 20, fontWeight: '600', marginRight: 52 }}>{title}</Text>
        {onClose ? <View style={{ position: 'absolute', right: 16 }}><SheetCloseButton onPress={onClose} color={titleColor} /></View> : null}
      </View> : null}
      {children}
    </View></SheetHost>
  </SheetContainer>;
}
