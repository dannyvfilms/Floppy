import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { ApiDocs } from '../errors/ApiDocs';
import { ErrorRecovery, ErrorStatusSelector } from '../errors/ErrorRecovery';

export const errorsLabels = {
  apiDocs: 'API documentation',
  statusSelector: 'Choose an error page example',
};

// Error-page composition: status examples, recovery checks and copyable
// diagnostics. `/api/docs/` composes the same ApiDocs view as its own page.
export function ErrorsView({
  statuses = [],
  selected,
  onSelectStatus,
  notice = null,
  error = {},
  recovery = {},
  labels = {},
  palette = {},
  icons = {},
}) {
  const copy = { ...errorsLabels, ...(labels || {}) };
  return <View style={styles.page}>
    {statuses.length ? <ErrorStatusSelector options={statuses} selected={selected}
      onSelect={onSelectStatus} palette={palette} accessibilityLabel={copy.statusSelector} /> : null}
    {notice}
    <ErrorRecovery {...error} {...recovery} labels={recovery.labels || labels}
      palette={palette} icons={icons} />
  </View>;
}

// The API documentation page body. `model` is the server-built reference model;
// the adapter supplies clipboard and link intents.
export function ApiDocsView({
  model = {},
  labels = {},
  palette = {},
  onOpenLink,
  onCopy,
}) {
  const copy = { ...errorsLabels, ...(labels || {}) };
  return <View style={styles.page}>
    <Text role="heading" aria-level={2} style={[styles.heading, { color: palette.text || '#fafafa' }]}>{copy.apiDocs}</Text>
    <ApiDocs model={model} labels={labels} palette={palette}
      onOpenLink={onOpenLink} onCopy={onCopy} />
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 16, minWidth: 0 },
  heading: { fontSize: 22, fontWeight: '700', lineHeight: 28 },
});
