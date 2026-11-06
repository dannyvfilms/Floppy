import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { mountRoot } from '../settings/root';
import { readThemePalette, submitNativeForm } from './transport.web';

// The small account-backed manual import action. It has no card of its own.
export function AccountImportAction({ model, palette }) {
  const colors = { ...readThemePalette(), ...palette };
  return <View style={styles.stack}>
    <Text style={[styles.copy, { color: colors.textSecondary }]}>{model.description}</Text>
    <View style={styles.actions}>
      <Button
        label={model.label}
        onPress={model.href
          ? () => window.location.assign(model.href)
          : () => submitNativeForm({
            action: model.action,
            csrf: model.csrf,
            returnTo: model.next,
            values: {},
          })}
      />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 10 },
  copy: { fontSize: 13, lineHeight: 19 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});

export function mountAccountImportAction(host, model) {
  return mountRoot(host, <AccountImportAction model={model} />);
}
