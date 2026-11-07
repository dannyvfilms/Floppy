import { Modal } from './Modal';
import React, { useEffect, useRef, useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Reveal } from './Reveal';

// The signed-in sidebar as shared React Native presentation. The browser
// adapter supplies links, storage, drag and transport; this file only lays out
// the logo, media-type groups, pinned lists, onboarding slot and bottom actions.

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d1d5db',
  textMuted: '#adb5bd',
  surface: '#2a2f35',
  surfaceStrong: '#343a40',
  surfaceHover: '#3f3f46',
  hoverDim: 'rgba(255, 255, 255, 0.05)',
  border: '#343a40',
  link: '#818cf8',
  danger: '#ef4444',
  sidebar: '#212529',
  overlay: 'rgba(0, 0, 0, 0.5)',
  focusStyle: {},
  radius: 6,
  navRowHeight: 36,
  navFontSize: 14,
  navIconSize: 20,
};

const defaultLabels = {
  logo: 'Floppy',
  explore: 'Explore',
  logout: 'Logout',
  pinnedLists: 'Pinned lists',
  navOptions: 'Navigation options',
  pin: 'Pin to sidebar',
  unpin: 'Unpin from sidebar',
  listOptions: 'List options',
  reorder: 'Reorder',
  delete: 'Delete',
  done: 'Done',
  closeMenu: 'Close menu',
  navigation: 'Navigation',
  savedViews: 'Saved %(name)s views',
  viewOptions: 'Options for %(name)s',
  confirmDelete: 'Delete the saved view \u201c%(name)s\u201d?',
};

const controlGlyphs = {
  chevron: '\u2304',
  ellipsis: '\u2026',
  drag: '\u2195',
  reorder: '\u21c5',
  trash: '\u232b',
  check: '\u2713',
  close: '\u00d7',
};

const format = (template, name) => template.replace('%(name)s', name);

function IconSlot({ spec, glyph, renderIcon, size = 20, color, rotate }) {
  const transform = rotate ? [{ rotate }] : undefined;
  if (renderIcon && spec) {
    return <View style={{ width: size, height: size, alignItems: 'center',
      justifyContent: 'center', color, fontSize: size, transform }}>
      {renderIcon(spec, { size, color })}
    </View>;
  }
  return <Text aria-hidden style={{ fontSize: size, lineHeight: size + 2, color, transform }}>
    {glyph || '\u2022'}
  </Text>;
}

function MenuModal({ open, onClose, children, palette, labels }) {
  return <Modal transparent visible={open} animationType="fade" onRequestClose={onClose}>
    <View style={styles.modalRoot}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.closeMenu}
        onPress={onClose} style={[StyleSheet.absoluteFill, { backgroundColor: palette.overlay }]} />
      <View accessibilityViewIsModal style={[styles.menu, {
        backgroundColor: palette.surfaceStrong, borderColor: palette.border,
      }]}>{children}</View>
    </View>
  </Modal>;
}

function MenuButton({ label, onPress, palette, danger = false, icon, glyph, renderIcon }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
    style={({ pressed }) => [styles.menuItem, pressed && { backgroundColor: palette.surfaceHover }]}>
    {icon || glyph ? <IconSlot spec={icon} glyph={glyph} renderIcon={renderIcon} size={16}
      color={danger ? palette.danger : palette.textSecondary} /> : null}
    <Text style={[styles.menuItemText, { color: danger ? palette.danger : palette.textSecondary }]}>
      {label}
    </Text>
  </Pressable>;
}

function PinMenu({ pinKey, pins, palette, labels, icons, renderIcon }) {
  const [open, setOpen] = useState(false);
  const pinned = pins.isPinned(pinKey);
  return <View style={styles.action}>
    <Pressable accessibilityRole="button" accessibilityLabel={labels.navOptions}
      accessibilityState={{ expanded: open }} onPress={() => setOpen(value => !value)}
      style={({ pressed }) => [styles.iconButton, { borderRadius: palette.radius },
        pressed && { backgroundColor: palette.hoverDim }]}>
      <IconSlot spec={icons?.ellipsis} glyph={controlGlyphs.ellipsis} renderIcon={renderIcon}
        size={16} color={palette.textMuted} />
    </Pressable>
    <MenuModal open={open} onClose={() => setOpen(false)} palette={palette} labels={labels}>
      <MenuButton label={pinned ? labels.unpin : labels.pin} palette={palette}
        onPress={() => { pins.toggle(pinKey); setOpen(false); }} />
    </MenuModal>
  </View>;
}

function HoverRow({ active, palette, rowActions = 'always', children, actions, style, ...rest }) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const reveal = rowActions !== 'always';
  const visible = !reveal || hovered || focused;
  const hoverProps = reveal ? {
    onPointerEnter: () => setHovered(true),
    onPointerLeave: () => setHovered(false),
  } : {};
  const focusProps = reveal ? {
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
  } : {};
  return <View {...rest} {...hoverProps}
    style={[styles.row, style, { borderTopLeftRadius: palette.radius, borderTopRightRadius: palette.radius,
        borderBottomLeftRadius: palette.radius, borderBottomRightRadius: palette.radius, minHeight: palette.navRowHeight, overflow: 'hidden' },
      hovered && !active && { backgroundColor: palette.hoverDim },
      active && { backgroundColor: palette.border }]}>
    {children}
    {actions ? <View {...focusProps}
      style={[styles.rowActions, { opacity: visible ? 1 : 0 }]}>{actions}</View> : null}
  </View>;
}

function LinkRow({ item, palette, labels, renderIcon, onNavigate, rowActions, action }) {
  const link = item.platformProps || {};
  const webLink = Boolean(link.href);
  return <HoverRow active={item.active} palette={palette} rowActions={rowActions} actions={action}>
    <Pressable {...link} accessibilityRole="link"
      accessibilityLabel={item.label} accessibilityState={{ selected: item.active }}
      onPress={webLink ? undefined : () => onNavigate?.(item)}
      style={({ pressed, focused }) => [styles.link, { minHeight: palette.navRowHeight },
        pressed && !webLink && { backgroundColor: palette.hoverDim },
        focused && palette.focusStyle]}>
      <IconSlot spec={item.icon} glyph={item.glyph} renderIcon={renderIcon} size={palette.navIconSize}
        color={item.active ? palette.link : palette.textMuted} />
      <Text numberOfLines={1} style={[styles.linkText,
        { color: item.active ? palette.text : palette.textMuted, fontSize: palette.navFontSize }]}>{item.label}</Text>
    </Pressable>
  </HoverRow>;
}

function SavedViewGroup({
  item, pins, palette, labels, renderIcon, rowActions, onNavigate, icons,
  enableSortable, onToggleGroup, onDeleteView, onFinishReorder,
}) {
  const [open, setOpen] = useState(Boolean(item.open));
  const [reordering, setReordering] = useState(false);
  const [views, setViews] = useState(item.views);
  const [menuFor, setMenuFor] = useState(null);
  const list = useRef(null);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    onToggleGroup?.(item.key, next);
  };

  useEffect(() => {
    if (!reordering || !enableSortable || !list.current) return undefined;
    return enableSortable(list.current, (from, to) => {
      setViews(current => {
        const next = [...current];
        next.splice(to, 0, next.splice(from, 1)[0]);
        return next;
      });
    });
  }, [reordering, enableSortable]);

  const menuView = menuFor == null ? null : views.find(view => view.id === menuFor);
  const finish = () => {
    setReordering(false);
    onFinishReorder?.(item.key, views);
  };

  const actions = <React.Fragment>
    <Pressable accessibilityRole="button"
      accessibilityLabel={format(labels.savedViews, item.label)}
      accessibilityState={{ expanded: open }} onPress={toggle}
      style={({ pressed }) => [styles.iconButton, { borderRadius: palette.radius },
        pressed && { backgroundColor: palette.hoverDim }]}>
      <IconSlot spec={icons?.chevron} glyph={controlGlyphs.chevron} renderIcon={renderIcon}
        size={16} color={palette.textMuted} rotate={open ? '0deg' : '-90deg'} />
    </Pressable>
    {item.pinKey ? <PinMenu pinKey={item.pinKey} pins={pins} palette={palette} labels={labels}
      icons={icons} renderIcon={renderIcon} /> : null}
  </React.Fragment>;

  return <View>
    <HoverRow active={item.active} palette={palette} rowActions={rowActions} actions={actions}>
      <Pressable {...(item.platformProps || {})} accessibilityRole="link"
        accessibilityLabel={item.label} accessibilityState={{ selected: item.active }}
        onPress={item.platformProps?.href ? undefined : () => onNavigate?.(item)}
        style={({ focused }) => [styles.link, { minHeight: palette.navRowHeight }, focused && palette.focusStyle]}>
        <IconSlot spec={item.icon} glyph={item.glyph} renderIcon={renderIcon} size={palette.navIconSize}
          color={item.active ? palette.link : palette.textMuted} />
        <Text numberOfLines={1} style={[styles.linkText,
          { color: item.active ? palette.text : palette.textMuted, fontSize: palette.navFontSize }]}>{item.label}</Text>
      </Pressable>
    </HoverRow>
    {open ? <View ref={list} style={styles.savedViewList}>
      {views.map(view => <SavedViewRow key={view.id} view={view} reordering={reordering}
        palette={palette} labels={labels} rowActions={rowActions} icons={icons}
        renderIcon={renderIcon} onNavigate={onNavigate} onMenu={() => setMenuFor(view.id)} />)}
      {reordering ? <Pressable accessibilityRole="button" accessibilityLabel={labels.done}
        onPress={finish} style={({ pressed }) => [styles.doneButton,
          { borderRadius: palette.radius }, pressed && { backgroundColor: palette.hoverDim }]}>
        <IconSlot spec={icons?.check} glyph={controlGlyphs.check} renderIcon={renderIcon}
          size={16} color={palette.link} />
        <Text style={[styles.doneText, { color: palette.link }]}>{labels.done}</Text>
      </Pressable> : null}
    </View> : null}
    <MenuModal open={Boolean(menuView)} onClose={() => setMenuFor(null)}
      palette={palette} labels={labels}>
      {menuView ? <React.Fragment>
        <MenuButton label={labels.reorder} palette={palette} icon={icons?.reorder}
          glyph={controlGlyphs.reorder} renderIcon={renderIcon}
          onPress={() => { setMenuFor(null); setOpen(true); setReordering(true); }} />
        <MenuButton label={labels.delete} palette={palette} danger icon={icons?.trash}
          glyph={controlGlyphs.trash} renderIcon={renderIcon}
          onPress={() => { setMenuFor(null); onDeleteView?.(menuView); }} />
      </React.Fragment> : null}
    </MenuModal>
  </View>;
}

function SavedViewRow({ view, reordering, palette, labels, rowActions, icons, renderIcon, onNavigate, onMenu }) {
  const actions = reordering ? null : <Pressable accessibilityRole="button"
    accessibilityLabel={format(labels.viewOptions, view.name)}
    onPress={onMenu} style={({ pressed }) => [styles.iconButton, { borderRadius: palette.radius },
      pressed && { backgroundColor: palette.hoverDim }]}>
    <IconSlot spec={icons?.ellipsis} glyph={controlGlyphs.ellipsis} renderIcon={renderIcon}
      size={16} color={palette.textMuted} />
  </Pressable>;
  return <HoverRow testID={`saved-view-row-${view.id}`} active={view.current} palette={palette}
    rowActions={rowActions} actions={actions} style={styles.savedViewRow}>
    {reordering ? <View testID="saved-view-handle" style={styles.dragHandle}>
      <IconSlot spec={icons?.drag} glyph={controlGlyphs.drag} renderIcon={renderIcon}
        size={16} color={palette.textMuted} />
    </View> : null}
    <Pressable {...(reordering ? {} : view.platformProps || {})} accessibilityRole="link"
      accessibilityLabel={view.name} accessibilityState={{ selected: view.current }}
      {...(view.platformProps?.href ? { 'aria-current': view.current ? 'page' : undefined } : {})}
      disabled={reordering}
      onPress={view.platformProps?.href ? undefined : () => onNavigate?.(view)}
      style={({ focused }) => [styles.savedViewLink, focused && palette.focusStyle]}>
      <Text numberOfLines={1} style={[styles.savedViewText,
        { color: view.current ? palette.text : palette.textMuted }]}>{view.name}</Text>
    </Pressable>
  </HoverRow>;
}

function ListsItem({
  item, pins, model, palette, labels, renderIcon, rowActions, onNavigate, icons,
  onToggleLists, onUnpinList,
}) {
  const initial = Boolean(item.open);
  const [open, setOpen] = useState(initial);
  const [menuFor, setMenuFor] = useState(null);
  const count = useRef(pins.pinnedLists.length);
  const current = pins.pinnedLists.some(entry => entry.url === model.currentUrl);
  const expanded = open || current;

  useEffect(() => {
    if (pins.pinnedLists.length > count.current) setOpen(true);
    count.current = pins.pinnedLists.length;
  }, [pins.pinnedLists.length]);

  const toggle = () => {
    const next = !expanded;
    setOpen(next);
    onToggleLists?.(next);
  };

  const menuEntry = menuFor == null ? null : pins.pinnedLists.find(entry => entry.id === menuFor);

  const actions = <React.Fragment>
    {pins.pinnedLists.length > 0 ? <Pressable accessibilityRole="button"
      accessibilityLabel={labels.pinnedLists} accessibilityState={{ expanded }}
      onPress={toggle} style={({ pressed }) => [styles.iconButton, { borderRadius: palette.radius },
        pressed && { backgroundColor: palette.hoverDim }]}>
      <IconSlot spec={icons?.chevron} glyph={controlGlyphs.chevron} renderIcon={renderIcon}
        size={16} color={palette.textMuted} rotate={expanded ? '0deg' : '-90deg'} />
    </Pressable> : null}
    <PinMenu pinKey="lists" pins={pins} palette={palette} labels={labels}
      icons={icons} renderIcon={renderIcon} />
  </React.Fragment>;

  return <View>
    <HoverRow active={item.active} palette={palette} rowActions={rowActions} actions={actions}>
      <Pressable {...(item.platformProps || {})} accessibilityRole="link"
        accessibilityLabel={item.label} accessibilityState={{ selected: item.active }}
        onPress={item.platformProps?.href ? undefined : () => onNavigate?.(item)}
        style={({ focused }) => [styles.link, { minHeight: palette.navRowHeight }, focused && palette.focusStyle]}>
        <IconSlot spec={item.icon} glyph={item.glyph} renderIcon={renderIcon} size={palette.navIconSize}
          color={item.active ? palette.link : palette.textMuted} />
        <Text numberOfLines={1} style={[styles.linkText,
          { color: item.active ? palette.text : palette.textMuted, fontSize: palette.navFontSize }]}>{item.label}</Text>
      </Pressable>
    </HoverRow>
    {expanded ? <View style={styles.savedViewList}>
      {pins.pinnedLists.map(entry => <View key={entry.id}
        style={[styles.savedViewRow, { backgroundColor: 'transparent' }]}>
        <Pressable {...(entry.platformProps || {})} accessibilityRole="link"
          accessibilityLabel={entry.name}
          onPress={entry.platformProps?.href ? undefined : () => onNavigate?.({ ...entry, href: entry.url })}
          style={styles.savedViewLink}>
          <Text numberOfLines={1} style={[styles.savedViewText,
            { color: palette.textMuted }]}>{entry.name}</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={labels.listOptions}
          onPress={() => setMenuFor(entry.id)}
          style={({ pressed }) => [styles.iconButton, { borderRadius: palette.radius },
            pressed && { backgroundColor: palette.hoverDim }]}>
          <IconSlot spec={icons?.ellipsis} glyph={controlGlyphs.ellipsis} renderIcon={renderIcon}
            size={16} color={palette.textMuted} />
        </Pressable>
      </View>)}
    </View> : null}
    <MenuModal open={Boolean(menuEntry)} onClose={() => setMenuFor(null)}
      palette={palette} labels={labels}>
      {menuEntry ? <MenuButton label={labels.unpin} palette={palette}
        onPress={() => { setMenuFor(null); onUnpinList?.(menuEntry.id); }} /> : null}
    </MenuModal>
  </View>;
}

function BottomLink({ item, palette, renderIcon, onNavigate }) {
  return <Pressable {...(item.platformProps || {})} accessibilityRole={item.platformProps?.href ? 'link' : 'button'}
    accessibilityLabel={item.label}
    onPress={item.platformProps?.href ? undefined : () => onNavigate?.(item)}
    style={({ pressed, hovered, focused }) => [styles.bottomLink, { borderTopLeftRadius: palette.radius, borderTopRightRadius: palette.radius,
        borderBottomLeftRadius: palette.radius, borderBottomRightRadius: palette.radius, minHeight: palette.navRowHeight },
      (pressed || hovered) && { backgroundColor: palette.hoverDim },
      focused && palette.focusStyle]}>
    <IconSlot spec={item.icon} glyph={item.glyph} renderIcon={renderIcon} size={palette.navIconSize}
      color={item.active ? palette.link : palette.textMuted} />
    <Text style={[styles.linkText, { color: item.active ? palette.text : palette.textMuted, fontSize: palette.navFontSize }]}>
      {item.label}
    </Text>
  </Pressable>;
}

export function Sidebar({
  model,
  pins = { pinned: [], pinnedLists: [], isPinned: () => false, toggle: () => {}, unpinList: () => {} },
  renderIcon,
  onNavigate,
  onToggleGroup,
  onToggleLists,
  onUnpinList,
  onDeleteView,
  onFinishReorder,
  enableSortable,
  onLogout,
  onboarding,
  rowActions = 'always',
  showLogo = true,
  autoScrollExplore = true,
  labels: labelOverrides,
  palette: paletteOverrides,
  style,
}) {
  const labels = { ...defaultLabels, ...labelOverrides };
  const palette = { ...defaultPalette, ...paletteOverrides };
  const [navOpen, setNavOpen] = useState(false);
  const list = useRef(null);
  const hasUnpinned = model.pinKeys.some(key => !pins.isPinned(key));
  const unpinned = model.secondary.filter(item => !pins.isPinned(item.pinKey));
  const pinned = model.secondary.filter(item => pins.isPinned(item.pinKey));
  const secondaryVisible = navOpen || pinned.length > 0;

  const toggleNav = () => {
    const next = !navOpen;
    setNavOpen(next);
    if (next && autoScrollExplore) setTimeout(() => list.current?.scrollToEnd?.({ animated: false }), 0);
  };

  const renderItem = item => {
    if (item.type === 'group') {
      return <SavedViewGroup key={item.key} item={item} pins={pins} palette={palette}
        labels={labels} renderIcon={renderIcon} rowActions={rowActions} icons={model.icons}
        onNavigate={onNavigate} enableSortable={enableSortable} onToggleGroup={onToggleGroup}
        onDeleteView={onDeleteView} onFinishReorder={onFinishReorder} />;
    }
    if (item.type === 'lists') {
      return <ListsItem key="lists" item={item} pins={pins} model={model}
        palette={palette} labels={labels} renderIcon={renderIcon} rowActions={rowActions}
        icons={model.icons} onNavigate={onNavigate} onToggleLists={onToggleLists}
        onUnpinList={onUnpinList || pins.unpinList} />;
    }
    return <LinkRow key={item.href} item={item} palette={palette} labels={labels}
      renderIcon={renderIcon} onNavigate={onNavigate} rowActions={rowActions}
      action={item.pinKey ? <PinMenu pinKey={item.pinKey} pins={pins}
        palette={palette} labels={labels} icons={model.icons} renderIcon={renderIcon} /> : null} />;
  };

  const logo = model.logo || {};

  return <View style={[styles.root, { backgroundColor: palette.sidebar }, style]}>
    {showLogo ? <View style={[styles.header, { borderBottomColor: palette.border }]}>
      {logo.src
        ? <Image accessible accessibilityLabel={logo.alt || labels.logo}
          resizeMode={logo.mono ? 'cover' : 'contain'} source={{ uri: logo.src }}
          style={logo.mono ? styles.logoMono : styles.logo} />
        : <Text style={[styles.logoText, { color: palette.text }]}>{logo.text || labels.logo}</Text>}
    </View> : null}
    <ScrollView ref={list} style={styles.primary}
      contentContainerStyle={[styles.navContent, {
        paddingTop: palette.navContentPaddingTop ?? 16,
        paddingRight: palette.navContentPaddingRight ?? 16,
      }]}
      onContentSizeChange={() => { if (navOpen && autoScrollExplore) list.current?.scrollToEnd?.({ animated: false }); }}>
      {model.primary.map(item => renderItem({ ...item, pinKey: null }))}
      <View style={[secondaryVisible && styles.secondary, { borderTopColor: palette.border }]}>
        <Reveal open={navOpen}>
          <View style={styles.navGroup}>{unpinned.map(renderItem)}</View>
        </Reveal>
        <View style={styles.navGroup}>{pinned.map(renderItem)}</View>
      </View>
    </ScrollView>
    <View>{onboarding}</View>
    <View style={[styles.bottom, { borderTopColor: palette.border }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.explore}
        accessibilityState={{ expanded: navOpen, disabled: !hasUnpinned }}
        onPress={hasUnpinned ? toggleNav : undefined}
        style={({ pressed, hovered, focused }) => [styles.explore, { borderTopLeftRadius: palette.radius, borderTopRightRadius: palette.radius,
        borderBottomLeftRadius: palette.radius, borderBottomRightRadius: palette.radius, minHeight: palette.navRowHeight },
          !hasUnpinned && styles.exploreReserved,
          (pressed || hovered) && hasUnpinned && { backgroundColor: palette.hoverDim },
          focused && hasUnpinned && palette.focusStyle]}>
        <IconSlot spec={model.icons?.chevron} glyph={controlGlyphs.chevron} renderIcon={renderIcon}
          size={palette.navIconSize} color={palette.textMuted} rotate={navOpen ? '0deg' : '180deg'} />
        <Text style={[styles.linkText, { color: palette.textMuted, fontSize: palette.navFontSize }]}>{labels.explore}</Text>
      </Pressable>
      <BottomLink item={model.bottom.settings} palette={palette}
        renderIcon={renderIcon} onNavigate={onNavigate} />
      <Pressable accessibilityRole="button" accessibilityLabel={labels.logout} onPress={onLogout}
        style={({ pressed, hovered, focused }) => [styles.bottomLink, { borderTopLeftRadius: palette.radius, borderTopRightRadius: palette.radius,
        borderBottomLeftRadius: palette.radius, borderBottomRightRadius: palette.radius, minHeight: palette.navRowHeight },
          (pressed || hovered) && { backgroundColor: palette.hoverDim },
          focused && palette.focusStyle]}>
        <IconSlot spec={model.bottom.logoutIcon} glyph={model.bottom.logoutGlyph}
          renderIcon={renderIcon} size={palette.navIconSize} color={palette.textMuted} />
        <Text style={[styles.linkText, { color: palette.textMuted, fontSize: palette.navFontSize }]}>{labels.logout}</Text>
      </Pressable>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { flex: 1, minHeight: 0, flexDirection: 'column' },
  header: { height: 64, flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 24, borderBottomWidth: 1 },
  logo: { width: 118, height: 36 },
  logoMono: { width: 158, height: 36 },
  logoText: { fontSize: 20, fontWeight: '700', letterSpacing: 0.2 },
  primary: { flex: 1, minHeight: 0 },
  navContent: { padding: 16, gap: 4 },
  navGroup: { gap: 4 },
  secondary: { borderTopWidth: 1, marginTop: 4, paddingTop: 4 },
  secondaryScroll: { minHeight: 0 },
  secondaryContent: { width: '100%' },
  row: { minHeight: 36, flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'transparent' },
  rowActions: { position: 'absolute', right: 8, top: 0, bottom: 0,
    flexDirection: 'row', alignItems: 'center' },
  link: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center',
    gap: 12, paddingHorizontal: 16, paddingVertical: 8 },
  linkText: { flexShrink: 1, fontSize: 14 },
  action: { flexShrink: 0, marginRight: 8 },
  iconButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  savedViewList: { marginTop: 4, marginLeft: 32, gap: 4 },
  savedViewRow: { minHeight: 32, flexDirection: 'row', alignItems: 'center',
    paddingLeft: 12, paddingRight: 4 },
  savedViewLink: { flex: 1, minWidth: 0, paddingVertical: 6 },
  savedViewText: { flexShrink: 1, fontSize: 14 },
  dragHandle: { width: 24, alignItems: 'center', justifyContent: 'center' },
  doneButton: { flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingLeft: 12, paddingRight: 4, paddingVertical: 6 },
  doneText: { fontSize: 14 },
  bottom: { padding: 16, borderTopWidth: 1, gap: 8 },
  explore: { flexDirection: 'row', alignItems: 'center', gap: 12,
    paddingHorizontal: 16, paddingVertical: 8, borderRadius: 6, minHeight: 36 },
  exploreReserved: { opacity: 0, pointerEvents: 'none' },
  bottomLink: { flexDirection: 'row', alignItems: 'center', gap: 12,
    paddingHorizontal: 16, paddingVertical: 8, borderRadius: 6 },
  modalRoot: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  menu: { width: 208, borderRadius: 8, borderWidth: 1, paddingVertical: 4 },
  menuItem: { flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: 12, paddingVertical: 10 },
  menuItemText: { fontSize: 14 },
});
