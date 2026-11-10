import React, { useEffect, useLayoutEffect, useState } from 'react';
import { AccessibilityInfo, LayoutAnimation, StyleSheet, useWindowDimensions, View } from 'react-native';
import { Stack } from 'expo-router';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import { useHinge } from 'expo-hinge';
import { ArrangementView, Host, RNHostView } from '@expo/ui/swift-ui';
import { arrangementViewStyle, frame } from '@expo/ui/swift-ui/modifiers';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ReservedRegionsProvider, useReservedRegions } from 'react-native-reserved-regions';
import { useVerticalBarEdgeIOS } from 'expo-status-bar';
import { RailModalHost, RailModalProvider, useRailModal } from '../../../frontend/ui/Modal';
import { menuGeometry } from './menuGeometry.mjs';
import { horizontalContentPadding } from '../safeAreaSpacing.mjs';

function MenuLayout({ open, sidebar, search, children, palette, division, reduceMotion, onFull }) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [contentWidth, setContentWidth] = useState(0);
  const [arrangement, setArrangement] = useState(null);
  const hinge = useHinge();
  const measuredDivision = division?.frame || (arrangement?.containerWidth === contentWidth ? arrangement : null);
  const target = menuGeometry(contentWidth || width, hinge?.status, measuredDivision);
  const [geometry, setGeometry] = useState(target);
  useLayoutEffect(() => {
    if (geometry.full === target.full && geometry.menuWidth === target.menuWidth && geometry.gap === target.gap) return;
    if (open && !reduceMotion && (hinge?.status === 'fullyOpen' || hinge?.status === 'partiallyOpen')) {
      LayoutAnimation.configureNext({ duration: 220, update: { type: LayoutAnimation.Types.easeOut } });
    }
    setGeometry(target);
  }, [geometry, target.full, target.menuWidth, target.gap, hinge?.status, open, reduceMotion]);
  useEffect(() => { onFull?.(geometry.full); }, [geometry.full, onFull]);
  return <View style={styles.row} onLayout={event => setContentWidth(event.nativeEvent.layout.width)}>
    {Constants.executionEnvironment === ExecutionEnvironment.StoreClient && hinge?.status === 'partiallyOpen'
      ? <Host pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
        style={StyleSheet.absoluteFill}>
        <ArrangementView modifiers={[arrangementViewStyle('split', { axes: 'horizontal' }), frame({ maxWidth: Infinity, maxHeight: Infinity })]}>
          <ArrangementView.Primary><RNHostView onLayout={event => {
            const measured = event.nativeEvent.layout;
            if (measured.width > 0 && measured.width < contentWidth) {
              setArrangement(current => current?.x === measured.width && current?.containerWidth === contentWidth
                ? current : { x: measured.width, width: 0, containerWidth: contentWidth });
            }
          }}><View style={styles.root} /></RNHostView></ArrangementView.Primary>
          <ArrangementView.Secondary><RNHostView><View style={styles.root} /></RNHostView></ArrangementView.Secondary>
        </ArrangementView>
      </Host> : null}
    <View accessibilityElementsHidden={!open} importantForAccessibility={open ? 'auto' : 'no-hide-descendants'}
      pointerEvents={open ? 'auto' : 'none'}
      style={[styles.sidebar, { backgroundColor: palette.sidebar, width: geometry.menuWidth,
        left: open ? 0 : -geometry.menuWidth }]}>
      {sidebar}
    </View>
    <View style={[styles.content, { marginLeft: open && !geometry.full ? geometry.menuWidth + geometry.gap : 0 }]} accessibilityElementsHidden={open && geometry.full}
      importantForAccessibility={open && geometry.full ? 'no-hide-descendants' : 'auto'}>
      <View style={[styles.search, horizontalContentPadding(insets, 22)]}>{search}</View>
      {children}
    </View>
  </View>;
}

function MeasuredNativeShell(props) {
  const regions = useReservedRegions();
  const division = regions.find(region => region.kind === 'division'
    && region.frame.height > region.frame.width && region.frame.x > 0);
  const hinge = useHinge();
  const railEdge = useVerticalBarEdgeIOS();
  const hasRail = Boolean(hinge || railEdge);
  return <RailModalProvider enabled={hasRail}>
    <ShellWithRail {...props} division={division} hasRail={hasRail} />
  </RailModalProvider>;
}

function StoreClientNativeShell(props) {
  const hinge = useHinge();
  const railEdge = useVerticalBarEdgeIOS();
  const hasRail = Boolean(hinge || railEdge);
  return <RailModalProvider enabled={hasRail}>
    <ShellWithRail {...props} hasRail={hasRail} />
  </RailModalProvider>;
}

export default function NativeShell(props) {
  return Constants.executionEnvironment === ExecutionEnvironment.StoreClient
    ? <StoreClientNativeShell {...props} />
    : <ReservedRegionsProvider style={styles.root}><MeasuredNativeShell {...props} /></ReservedRegionsProvider>;
}

function ShellWithRail({ open, onToggle, sidebar, search, children, palette, hasRail, canGoBack, onBack, division }) {
  const modal = useRailModal()?.active;
  const insets = useSafeAreaInsets();
  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setReduceMotion).catch(() => {});
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduceMotion);
    return () => subscription.remove();
  }, []);
  // Animate both target frames in the same native transaction.
  const toggle = () => {
    if (!reduceMotion) LayoutAnimation.configureNext({ duration: 220,
      update: { type: LayoutAnimation.Types.easeOut } });
    onToggle();
  };
  const [menuFull, setMenuFull] = useState(false);
  const menu = { open, sidebar, search, palette, children, reduceMotion, onFull: setMenuFull };
  return <>
    <Stack.Screen options={{ headerShown: true, headerTransparent: true, headerShadowVisible: false,
      title: '', headerTitle: '', headerTintColor: palette.text, contentStyle: { backgroundColor: palette.background } }} />
    <Stack.Toolbar placement="right">
      {hasRail
        ? <Stack.Toolbar.Button icon={modal ? 'xmark' : 'line.3.horizontal'} tintColor={palette.text}
          onPress={modal ? modal.onRequestClose : toggle}
          accessibilityLabel={modal ? 'Close dialog' : open ? 'Close navigation' : 'Open navigation'} />
        : <Stack.Toolbar.Button icon={modal ? 'xmark' : 'line.3.horizontal.decrease'} tintColor={palette.text}
          onPress={modal ? modal.onRequestClose : toggle}
          accessibilityLabel={modal ? 'Close dialog' : open ? 'Close navigation' : 'Open navigation'} />}
      {canGoBack ? <Stack.Toolbar.Button icon="chevron.left" tintColor={palette.text}
        onPress={modal ? modal.onRequestClose : onBack} accessibilityLabel="Back" separateBackground /> : null}
    </Stack.Toolbar>
    <View style={[styles.root, { paddingTop: insets.top, paddingLeft: insets.left,
      paddingRight: insets.right, paddingBottom: hasRail ? 0 : insets.bottom },
      // A full-width menu runs through the side rail and the other insets, so they take its colour.
      open && menuFull && { backgroundColor: palette.sidebar }]}>
      <View style={styles.root}
        accessibilityElementsHidden={Boolean(modal)}
        importantForAccessibility={modal ? 'no-hide-descendants' : 'auto'}>
      {Constants.executionEnvironment === ExecutionEnvironment.StoreClient
        ? <MenuLayout {...menu} />
        : <MenuLayout {...menu} division={division} />}
      </View>
      <RailModalHost />
    </View>
  </>;
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  search: { zIndex: 2, width: '100%', minHeight: 44,
    justifyContent: 'center', paddingTop: 25, paddingBottom: 27 },
  row: { flex: 1, flexDirection: 'row', minHeight: 0, overflow: 'hidden' },
  sidebar: { position: 'absolute', left: 0, top: 0, bottom: 0, zIndex: 3, overflow: 'hidden' },
  content: { flex: 1, minWidth: 0, zIndex: 0 },
});
