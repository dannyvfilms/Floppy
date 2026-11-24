import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AccessibilityInfo, LayoutAnimation, PanResponder, StyleSheet, useWindowDimensions, View } from 'react-native';
import { Stack } from 'expo-router';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import { ArrangementView, Host, RNHostView } from '@expo/ui/swift-ui';
import { arrangementViewStyle, frame } from '@expo/ui/swift-ui/modifiers';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ReservedRegionsProvider, useReservedRegions } from 'react-native-reserved-regions';
import { useVerticalBarEdgeIOS } from 'expo-status-bar';
import { MenuButton } from '../../../frontend/ui/Shell';
import { RailModalHost, RailModalProvider, useRailModal } from '../../../frontend/ui/Modal';
import { menuGeometry } from './menuGeometry.mjs';
import { useDevicePose } from '../data/useDevicePose';
import { horizontalContentPadding } from '../safeAreaSpacing.mjs';
import { ShellLayoutContext } from './shellContext';

function MenuLayout({ open, sidebar, search, children, palette, division, reduceMotion, overlaySearch, inlineMenu, onToggle, menuLabel }) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [contentWidth, setContentWidth] = useState(0);
  const [arrangement, setArrangement] = useState(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [searchHeight, setSearchHeight] = useState(96);
  const pose = useDevicePose();
  const measuredDivision = division?.frame || (arrangement?.containerWidth === contentWidth ? arrangement : null);
  const target = menuGeometry(contentWidth || width, pose, measuredDivision);
  const [geometry, setGeometry] = useState(target);
  // The panel is part of one shape with the side rail: it reaches the screen edge through the
  // safe-area insets (the rail on a full-width menu) and slides in with the panel, so the rail
  // colour is never a separate jump or fade.
  const bleed = { top: insets.top, left: insets.left, right: geometry.full ? insets.right : 0 };
  useLayoutEffect(() => {
    if (geometry.full === target.full && geometry.menuWidth === target.menuWidth && geometry.gap === target.gap) return;
    if (open && !reduceMotion && (pose.hinged && pose.fold !== 'closed')) {
      LayoutAnimation.configureNext({ duration: 220, update: { type: LayoutAnimation.Types.easeOut } });
    }
    setGeometry(target);
  }, [geometry, target.full, target.menuWidth, target.gap, pose.fold, open, reduceMotion]);
  return <View style={styles.row} onLayout={event => setContentWidth(event.nativeEvent.layout.width)}>
    {Constants.executionEnvironment === ExecutionEnvironment.StoreClient && pose.fold === 'partial'
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
      style={[styles.sidebar, { backgroundColor: palette.sidebar, top: -bleed.top, width: geometry.menuWidth + bleed.left + bleed.right,
        left: open ? -bleed.left : -(geometry.menuWidth + bleed.left + bleed.right) }]}>
      {/* A full-width phone menu leaves the top row to the menu button that closes it. */}
      <View style={{ flex: 1, paddingTop: bleed.top + (inlineMenu && geometry.full ? 69 : 0), paddingLeft: bleed.left, paddingRight: bleed.right }}>
        {sidebar}
      </View>
    </View>
    <View onLayout={event => setViewport(event.nativeEvent.layout)}
      style={[styles.content, { marginLeft: open && !geometry.full ? geometry.menuWidth + geometry.gap : 0 }]} accessibilityElementsHidden={open && geometry.full}
      importantForAccessibility={open && geometry.full ? 'no-hide-descendants' : 'auto'}>
      <View onLayout={event => setSearchHeight(event.nativeEvent.layout.height)}
        style={[styles.search, horizontalContentPadding(insets, 22), overlaySearch && styles.searchOverlay]}>
        {inlineMenu
          // A phone has no rail, so the menu sits left of the search like the PWA top bar instead of
          // floating in the navigation bar over it. A Duo (hasRail) keeps its toolbar buttons.
          ? <View style={styles.searchRow}>
            <View style={styles.menuSlot} />
            <View style={styles.searchFill}>{search}</View>
          </View>
          : search}
      </View>
      <ShellLayoutContext.Provider value={{ ...viewport, insets,
        headerHeight: overlaySearch ? searchHeight : 0 }}>
        {children}
      </ShellLayoutContext.Provider>
    </View>
    {inlineMenu ? <View pointerEvents="box-none"
      style={[styles.inlineMenu, { left: Math.max(0, 22 - insets.left) }]}>
      <MenuButton open={open} onPress={onToggle} label={menuLabel} palette={palette} />
    </View> : null}
  </View>;
}

function MeasuredNativeShell(props) {
  const regions = useReservedRegions();
  const division = regions.find(region => region.kind === 'division'
    && region.frame.height > region.frame.width && region.frame.x > 0);
  const pose = useDevicePose();
  const railEdge = useVerticalBarEdgeIOS();
  const hasRail = Boolean(pose.hasHinge || railEdge);
  return <RailModalProvider enabled={hasRail}>
    <ShellWithRail {...props} division={division} hasRail={hasRail} />
  </RailModalProvider>;
}

function StoreClientNativeShell(props) {
  const pose = useDevicePose();
  const railEdge = useVerticalBarEdgeIOS();
  const hasRail = Boolean(pose.hasHinge || railEdge);
  return <RailModalProvider enabled={hasRail}>
    <ShellWithRail {...props} hasRail={hasRail} />
  </RailModalProvider>;
}

export default function NativeShell(props) {
  return Constants.executionEnvironment === ExecutionEnvironment.StoreClient
    ? <StoreClientNativeShell {...props} />
    : <ReservedRegionsProvider style={styles.root}><MeasuredNativeShell {...props} /></ReservedRegionsProvider>;
}

// A phone has no toolbar Back button; dragging in from the left edge goes back, as on iOS.
function EdgeSwipeBack({ onBack }) {
  const latest = useRef(onBack);
  latest.current = onBack;
  const responder = useRef(PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onPanResponderRelease: (_, drag) => {
      if (drag.dx > 60 && Math.abs(drag.dy) < drag.dx / 2) latest.current?.();
    },
  })).current;
  return <View {...responder.panHandlers} style={styles.edgeSwipe} />;
}

function ShellWithRail({ open, onToggle, sidebar, search, children, palette, hasRail, canGoBack, onBack, division, overlaySearch }) {
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
  const menu = { open, sidebar, search, palette, children, reduceMotion, overlaySearch,
    inlineMenu: !hasRail, onToggle: toggle, menuLabel: open ? 'Close navigation' : 'Open navigation' };
  return <>
    <Stack.Screen options={{ headerShown: true, headerTransparent: true, headerShadowVisible: false,
      title: '', headerTitle: '', headerTintColor: palette.text, contentStyle: { backgroundColor: palette.background } }} />
    {hasRail ? <Stack.Toolbar placement="right">
      <Stack.Toolbar.Button icon={modal ? 'xmark' : 'line.3.horizontal'} tintColor={palette.text}
        onPress={modal ? modal.onRequestClose : toggle}
        accessibilityLabel={modal ? 'Close dialog' : open ? 'Close navigation' : 'Open navigation'} />
      {canGoBack ? <Stack.Toolbar.Button icon="chevron.left" tintColor={palette.text}
        onPress={modal ? modal.onRequestClose : onBack} accessibilityLabel="Back" separateBackground /> : null}
    </Stack.Toolbar> : null}
    <View style={[styles.root, { paddingTop: insets.top, paddingLeft: insets.left,
      paddingRight: insets.right, paddingBottom: hasRail ? 0 : insets.bottom }]}>
      <View style={styles.root}
        accessibilityElementsHidden={Boolean(modal)}
        importantForAccessibility={modal ? 'no-hide-descendants' : 'auto'}>
      {Constants.executionEnvironment === ExecutionEnvironment.StoreClient
        ? <MenuLayout {...menu} />
        : <MenuLayout {...menu} division={division} />}
      </View>
      <RailModalHost />
      {!hasRail && canGoBack ? <EdgeSwipeBack onBack={onBack} /> : null}
    </View>
  </>;
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  search: { zIndex: 2, width: '100%', minHeight: 44,
    justifyContent: 'center', paddingTop: 25, paddingBottom: 27 },
  // Only Media Details paints beneath search; the reviewed Home/search shell stays in flow.
  edgeSwipe: { position: 'absolute', left: 0, top: 0, bottom: 0, width: 20, zIndex: 50 },
  // Above the full-width menu panel (zIndex 3) so the same button closes it; 25 matches the search padding.
  inlineMenu: { position: 'absolute', top: 25, height: 44, justifyContent: 'center', zIndex: 4 },
  menuSlot: { width: 40 },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  searchFill: { flex: 1, minWidth: 0 },
  searchOverlay: { position: 'absolute', top: 0, left: 0, right: 0 },
  // Not clipped: the menu panel extends through the safe-area insets.
  row: { flex: 1, flexDirection: 'row', minHeight: 0 },
  sidebar: { position: 'absolute', left: 0, top: 0, bottom: 0, zIndex: 3, overflow: 'hidden' },
  content: { flex: 1, minWidth: 0, zIndex: 0 },
});
