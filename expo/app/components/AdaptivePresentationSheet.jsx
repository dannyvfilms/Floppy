import React from 'react';
import { View } from 'react-native';
import { SheetCloseButton } from './SheetCloseButton';
import { SheetContainer, SheetHost, useNativeSheetClose } from './SheetHost';
import { useSheetInsets } from './useSheetInsets';
import { Title } from '../../../frontend/ui/Title';
import { RailModalHost, RailModalProvider } from '../../../frontend/ui/Modal';

// The system places the rail's close button at the sheet's top inset, this far above the centre of the 80pt header row.
const NATIVE_CLOSE_LIFT = 16;
// Android's native sheet offers half and full states rather than arbitrary detents.
// children may be a function of { rail }: true when railItems sit in the system rail, so the
// body can drop its own control for them.
export function AdaptivePresentationSheet({ children, title, onClose, titleColor = '#fff', snapPoints = ['half', 'full'],
  railItems, railValue, onRailChange, ...props }) {
  const insets = useSheetInsets();
  const railEdge = useNativeSheetClose(insets);
  const nativeClose = Boolean(railEdge && title && onClose);
  const rail = nativeClose && Boolean(railItems?.length);
  const body = typeof children === 'function' ? children({ rail }) : children;
  return <SheetContainer snapPoints={snapPoints} showDragIndicator contentPadding={0} {...props}>
    <SheetHost nativeClose={nativeClose} onClose={onClose}
      railItems={rail ? railItems : null} railValue={railValue} onRailChange={onRailChange}><RailModalProvider enabled><View style={{ flex: 1 }}>
      {title ? <View style={{ height: 80, paddingLeft: 16 + (nativeClose ? 0 : insets.left), paddingRight: 16, justifyContent: 'center', alignItems: 'flex-start' }}>
        <Title size="sheet" level={1} numberOfLines={1} color={titleColor}
          style={{ marginRight: 52, transform: [{ translateY: nativeClose ? -NATIVE_CLOSE_LIFT : 0 }] }}>{title}</Title>
        {onClose && !nativeClose ? <View style={{ position: 'absolute', right: 16 }}><SheetCloseButton onPress={onClose} color={titleColor} /></View> : null}
      </View> : null}
      <View style={{ flex: 1, paddingLeft: nativeClose ? 0 : insets.left, paddingRight: nativeClose ? 0 : insets.right,
        // The native rail reserves its full width; the sheet body previously extended 16pt into it.
        marginLeft: nativeClose && railEdge === 'left' ? -16 : 0,
        marginRight: nativeClose && railEdge === 'right' ? -16 : 0 }}>{body}</View>
      {/* Nested selectors must appear above the sheet, not behind its native controller. */}
      <RailModalHost />
    </View></RailModalProvider></SheetHost>
  </SheetContainer>;
}
