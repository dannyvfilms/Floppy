import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

const FALLBACK_TONES = {
  indigo: '#4f46e5',
  emerald: '#059669',
  amber: '#d97706',
  rose: '#e11d48',
};

const FALLBACK_PALETTE = {
  actionText: '#ffffff',
  actionTones: FALLBACK_TONES,
  overlay: 'rgba(0, 0, 0, 0.5)',
  reorder: 'rgba(79, 70, 229, 0.95)',
  focusStyle: {},
};

function resolveTone(palette, tone) {
  return palette?.actionTones?.[tone]
    || FALLBACK_TONES[tone]
    || palette?.link
    || FALLBACK_TONES.indigo;
}

function ActionGlyph({ action, palette }) {
  return <Text accessible={false} style={[styles.glyph, { color: palette.actionText }]}>
    {action.glyph || (action.title || '?').slice(0, 1).toUpperCase()}
  </Text>;
}

export function MediaCardActionButton({ action, palette, onAction, renderIcon }) {
  const colors = { ...FALLBACK_PALETTE, ...(palette || {}) };
  return <Pressable
    accessibilityRole={action.kind === 'link' ? 'link' : 'button'}
    accessibilityLabel={action.title}
    accessibilityState={{ disabled: !!action.disabled, busy: !!action.busy }}
    disabled={!!action.disabled}
    onPress={() => onAction?.(action)}
    style={({ hovered, pressed, focused }) => [
      styles.roundAction,
      {
        backgroundColor: resolveTone(colors, action.tone),
        opacity: action.disabled ? 0.45 : hovered || pressed ? 0.85 : 1,
      },
      focused && colors.focusStyle,
    ]}>
    {renderIcon ? renderIcon(action) : <ActionGlyph action={action} palette={colors} />}
  </Pressable>;
}

export function MediaCardActionRow({ actions, palette, onAction, renderIcon }) {
  if (!actions?.items?.length) return null;
  return <View style={styles.row}>
    {actions.items.map((action, index) => <MediaCardActionButton
      key={`${action.title}-${index}`}
      action={action}
      palette={palette}
      onAction={onAction}
      renderIcon={renderIcon} />)}
  </View>;
}

const REORDER_STEPS = [
  ['first', '<<'],
  ['back', '<'],
  ['next', '>'],
  ['last', '>>'],
];

export function MediaCardActions({
  actions,
  palette,
  labels = {},
  revealed = false,
  onOpen,
  onAction,
  onReorder,
  renderIcon,
}) {
  if (!actions?.items?.length || !revealed) return null;
  const colors = { ...FALLBACK_PALETTE, ...(palette || {}) };
  const ordering = actions.ordering;
  return <View style={styles.overlay}>
    <Pressable accessibilityRole="button" accessibilityLabel={labels.open || actions.title}
      onPress={onOpen} style={[StyleSheet.absoluteFill, { backgroundColor: colors.overlay }]} />
    <View style={styles.overlayBody}>
      {ordering
        ? <View style={styles.ordering}>
          <View style={styles.row}>
            {REORDER_STEPS.map(([step, text]) => <Pressable key={step}
              accessibilityRole="button" accessibilityLabel={ordering.labels?.[step]}
              onPress={() => onReorder?.(step)}
              style={({ hovered, pressed, focused }) => [styles.orderButton, {
                backgroundColor: colors.reorder,
                opacity: hovered || pressed ? 0.85 : 1,
              }, focused && colors.focusStyle]}>
              <Text style={[styles.orderText, { color: colors.actionText }]}>{text}</Text>
            </Pressable>)}
          </View>
          <View accessible accessibilityLabel={ordering.labels?.drag} style={styles.dragHandle}>
            {renderIcon
              ? renderIcon({ kind: 'drag', title: ordering.labels?.drag, icon: ordering.dragIcon })
              : <Text accessible={false} style={[styles.dragGlyph, { color: colors.actionText }]}>≡</Text>}
          </View>
        </View>
        : <MediaCardActionRow actions={actions} palette={colors} onAction={onAction} renderIcon={renderIcon} />}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 30,
    alignItems: 'center',
    justifyContent: 'center',
  },
  overlayBody: { maxWidth: '100%' },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 8 },
  roundAction: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  glyph: { fontSize: 15, fontWeight: '700' },
  ordering: { alignItems: 'center', gap: 6 },
  orderButton: {
    minWidth: 34,
    height: 32,
    paddingHorizontal: 8,
    borderRadius: 6,
    alignItems: 'center',
    justifyContent: 'center',
  },
  orderText: { fontSize: 13, fontWeight: '700' },
  dragHandle: { minHeight: 28, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center' },
  dragGlyph: { fontSize: 18, fontWeight: '700' },
});
