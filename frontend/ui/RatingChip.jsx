import React, { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { RatingStars } from './RatingStars';

const fallbackPalette = {
  lit: '#facc15',
  unlit: '#4b5563',
  cardUnlit: '#a1a1aa',
  muted: '#a1a1aa',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  surface: '#27272a',
  border: '#3f3f46',
  chipBackground: 'rgba(245, 158, 11, 0.07)',
  chipBorder: 'rgba(251, 191, 36, 0.18)',
  chipHoverBackground: 'rgba(245, 158, 11, 0.11)',
  chipHoverBorder: 'rgba(252, 211, 77, 0.28)',
  starBadgeBackground: 'rgba(245, 158, 11, 0.14)',
  starBadgeBorder: 'rgba(251, 191, 36, 0.28)',
  cardBackground: 'rgba(251, 191, 36, 0.10)',
  cardBorder: 'rgba(251, 191, 36, 0.26)',
  compactUnratedBorder: 'rgba(156, 163, 175, 0.28)',
  compactUnratedBackground: 'rgba(107, 114, 128, 0.14)',
  compactUnratedHoverBackground: 'rgba(107, 114, 128, 0.20)',
  compactRatedBorder: 'rgba(251, 191, 36, 0.28)',
  compactRatedBackground: 'rgba(245, 158, 11, 0.14)',
  compactRatedHoverBackground: 'rgba(245, 158, 11, 0.20)',
  compactValue: '#fcd34d',
  compactFontSize: 12,
  compactIconSize: 14,
  focusStyle: {},
  fontSize: 14,
  chipHeight: 32,
  starBadgeSize: 32,
  iconSize: 16,
  paddingRight: 12,
  gap: 8,
  popupWidth: 250,
  popupRadius: 8,
  popupPadding: 12,
};

const defaultLabels = {
  yourScore: 'Your score',
  derivedRating: 'Derived rating',
  editRating: 'Edit rating',
  addRating: 'Add rating',
  rate: 'Rate',
  derived: 'Derived',
  yourRating: 'Your rating',
  close: 'Close',
  prompt: 'Rate this item',
};

/**
 * The personal score chip and its rating popup.
 *
 * Presentation only: the caller owns the write, the popup anchor and the
 * platform theme. Selecting the current star again clears the score.
 */
export function RatingChip({
  value = null,
  scaleMax = 10,
  displayValue = null,
  cardDisplayValue = null,
  derived = null,
  layout = 'pill',
  labels,
  renderStar,
  onSelect,
  palette,
  open = false,
  onOpenChange,
  anchor = null,
}) {
  const [showCoverage, setShowCoverage] = useState(false);
  const colors = { ...fallbackPalette, ...palette };
  const text = { ...defaultLabels, ...labels };
  const rated = value !== null && value !== undefined;
  const hasDerived = Boolean(derived && derived.score !== null && derived.score !== undefined);
  const shown = displayValue ?? (rated ? String(value) : null);
  const cardShown = cardDisplayValue ?? shown;
  const star = (lit, size = 20) => renderStar?.(lit, size);
  const close = () => onOpenChange?.(false);
  const choose = score => {
    onSelect?.(score);
    close();
  };

  const popup = <Modal visible={open} transparent animationType="none" onRequestClose={close}>
    <View style={styles.modalRoot}>
      <Pressable accessible={false} style={StyleSheet.absoluteFill} onPress={close} />
      <View style={[styles.popup, {
        width: colors.popupWidth,
        borderRadius: colors.popupRadius,
        padding: colors.popupPadding,
        backgroundColor: colors.surface,
        borderColor: colors.border,
      }, anchor ? { position: 'absolute', left: anchor.left, top: anchor.top } : null]}>
        <RatingStars scaleMax={scaleMax} value={value} label={text.rate}
          renderStar={renderStar} onSelect={choose} palette={colors} />
      </View>
    </View>
  </Modal>;

  if (layout === 'compact') {
    return <View style={styles.root}>
      <Pressable accessibilityRole="button"
        accessibilityLabel={rated ? `${text.yourScore}: ${shown}` : text.addRating}
        accessibilityHint={rated ? text.editRating : text.addRating}
        title={text.rateTitle || text.rate}
        onPress={() => onOpenChange?.(!open)}
        style={({ hovered, pressed, focused }) => [styles.compactButton, {
          width: colors.starBadgeSize,
          height: colors.starBadgeSize,
          borderRadius: colors.starBadgeSize / 2,
          borderColor: rated ? colors.compactRatedBorder : colors.compactUnratedBorder,
          backgroundColor: hovered || pressed
            ? rated ? colors.compactRatedHoverBackground : colors.compactUnratedHoverBackground
            : rated ? colors.compactRatedBackground : colors.compactUnratedBackground,
        }, focused && colors.focusStyle]}>
        {rated
          ? <Text style={[styles.compactValue, { color: colors.compactValue, fontSize: colors.compactFontSize }]}>{shown}</Text>
          : <View style={{ color: colors.textSecondary }}>{star(false, colors.compactIconSize)}</View>}
      </Pressable>
      {popup}
    </View>;
  }

  if (layout === 'card') {
    return <View style={styles.root}>
      <View style={[styles.card, {
        height: colors.cardHeight || 93.75,
        borderColor: colors.cardBorder,
        backgroundColor: colors.cardBackground,
        borderRadius: colors.popupRadius + 4,
        paddingTop: colors.popupPadding + 2,
        paddingBottom: colors.popupPadding - 2,
        paddingHorizontal: colors.popupPadding,
      }]}>
        {rated
          ? <Pressable accessibilityRole="button" accessibilityLabel={`${text.yourScore}: ${cardShown}`}
            onPress={() => onOpenChange?.(!open)}
            style={({ hovered, pressed, focused }) => [styles.cardButton, (hovered || pressed) && styles.cardButtonActive, focused && colors.focusStyle]}>
            <View style={[styles.starBadge, {
              width: colors.starBadgeSize,
              height: colors.starBadgeSize,
              borderRadius: colors.starBadgeSize / 2,
              borderColor: colors.starBadgeBorder,
              backgroundColor: colors.starBadgeBackground,
            }]}>{star(true, colors.iconSize)}</View>
            <Text style={[styles.cardValue, { color: colors.text, fontSize: colors.fontSize }]}>{cardShown}</Text>
            <Text numberOfLines={1} style={[styles.cardMeta, { color: colors.textSecondary, fontSize: colors.fontSize }]}>
              {hasDerived ? `${text.derived} ${derived.score} · ${derived.coverage}` : text.yourRating}
            </Text>
          </Pressable>
          : <>
            <Text style={[styles.cardPrompt, { color: colors.textSecondary, fontSize: colors.fontSize }]}>
              {hasDerived ? `${text.derived} ${derived.score} · ${derived.coverage}` : text.prompt}
            </Text>
            <RatingStars scaleMax={scaleMax} value={value} label={text.rate}
              renderStar={lit => renderStar?.(lit, 16)}
              onSelect={score => onSelect?.(score)}
              palette={{ ...colors, unlit: colors.cardUnlit || colors.unlit }}
              showLabels={false} />
          </>}
      </View>
      {popup}
    </View>;
  }

  const coverageVisible = showCoverage;
  return <View style={styles.root}>
    <Pressable accessibilityRole="button"
      accessibilityLabel={rated
        ? hasDerived ? `${text.yourScore}: ${shown}. ${text.derivedRating}: ${derived.score}, ${derived.coverage}` : `${text.yourScore}: ${shown}`
        : hasDerived ? `${text.derivedRating}: ${derived.score}, ${derived.coverage}` : text.addRating}
      accessibilityHint={rated ? text.editRating : text.addRating}
      onPress={() => onOpenChange?.(!open)}
      onHoverIn={() => hasDerived && rated && setShowCoverage(true)}
      onHoverOut={() => setShowCoverage(false)}
      onFocus={() => hasDerived && rated && setShowCoverage(true)}
      onBlur={() => setShowCoverage(false)}
      style={({ hovered, pressed, focused }) => [styles.chip, {
        height: colors.chipHeight,
        paddingRight: colors.paddingRight,
        gap: colors.gap,
        borderColor: hovered || pressed ? colors.chipHoverBorder : colors.chipBorder,
        backgroundColor: hovered || pressed ? colors.chipHoverBackground : colors.chipBackground,
      }, focused && colors.focusStyle]}>
      <View style={[styles.starBadge, {
        width: colors.starBadgeSize,
        height: colors.starBadgeSize,
        borderRadius: colors.starBadgeSize / 2,
        borderColor: colors.starBadgeBorder,
        backgroundColor: colors.starBadgeBackground,
      }]}>{star(true, colors.iconSize)}</View>
      {hasDerived
        ? (rated
          ? <>
            <Text style={[styles.value, { color: colors.text, fontSize: colors.fontSize }]}>{shown}</Text>
            <Text style={[styles.divider, { color: colors.muted, fontSize: colors.fontSize }]}>|</Text>
            <Text style={[styles.derived, { color: colors.textSecondary, fontSize: colors.fontSize }]}>{derived.score}</Text>
            {coverageVisible
              ? <Text numberOfLines={1} style={[styles.coverage, { color: colors.textSecondary, fontSize: colors.fontSize }]}>· {derived.coverage}</Text>
              : null}
          </>
          : <>
            <Text style={[styles.value, { color: colors.text, fontSize: colors.fontSize }]}>{derived.score}</Text>
            <Text style={[styles.divider, { color: colors.muted, fontSize: colors.fontSize }]}>|</Text>
            <Text numberOfLines={1} style={[styles.derived, { color: colors.textSecondary, fontSize: colors.fontSize }]}>{derived.coverage}</Text>
          </>)
        : <>
          {rated
            ? <>
              <Text style={[styles.value, { color: colors.text, fontSize: colors.fontSize }]}>{shown}</Text>
              <Text style={[styles.divider, { color: colors.muted, fontSize: colors.fontSize }]}>|</Text>
            </>
            : null}
          <Text style={[styles.action, { color: colors.textSecondary, fontSize: colors.fontSize }]}>
            {rated ? text.editRating : text.addRating}
          </Text>
        </>}
    </Pressable>
    {popup}
  </View>;
}

const styles = StyleSheet.create({
  root: { alignSelf: 'flex-start', minWidth: 0 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    minWidth: 0,
    overflow: 'hidden',
    borderWidth: 1,
    borderRadius: 9999,
  },
  starBadge: { alignItems: 'center', justifyContent: 'center', flexShrink: 0, borderWidth: 1 },
  value: { fontWeight: '600' },
  divider: {},
  derived: { fontWeight: '500' },
  coverage: { fontWeight: '500' },
  action: { fontWeight: '500' },
  card: { width: '100%', justifyContent: 'center', gap: 6.4, borderWidth: 1 },
  cardPrompt: { fontWeight: '500', lineHeight: 21 },
  cardButton: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardButtonActive: {},
  cardValue: { fontWeight: '600' },
  cardMeta: { flexShrink: 1, fontWeight: '500' },
  compactButton: { alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  compactValue: { fontWeight: '700' },
  modalRoot: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  popup: { borderWidth: 1, overflow: 'hidden' },
});
