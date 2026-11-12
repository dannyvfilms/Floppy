import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { MediaCard } from '../../../frontend/ui/MediaCard';
import { mediaCardPalette, palette } from '../theme';
import { SettingsCardsView } from '../../../frontend/pages/SettingsCardsView';
import { cardsFromPayload } from '../data/settingsTransport';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

export const surface = {
  id: 'SET-CARDS',
  title: 'Media card layout editor',
  where: 'Settings media cards per-type line selection, order and preview',
  status: 'in_progress',
  note: 'The editor catalog (users.card_metadata.editor_catalog), the resolved per-type profiles and the touch-action toggle load from /api/v1/user/cards/ and save through PUT on the same route, which parses profiles with the same function the web form uses. Loading, signed-out and error-with-retry states are real. Browser and device runtime interaction were not exercised.',
};

const previewLabels = { altTitle: 'Show alternative title', nextEpisode: 'Jump to next episode', noStatus: 'No Status', rate: 'Rate', close: 'Close', open: 'Open' };

// The real card the server draws for this type with the draft profile (the web
// page fetches the same card), so lines, rating and title options are seen as saved.
function CardPreview({ transport, type, saved }) {
  const [state, setState] = useState({ card: null, error: '' });
  const draft = JSON.stringify(saved?.[type] || {});
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      transport.previewCard({ type, saved: { [type]: JSON.parse(draft) } })
        .then(response => live && setState({ card: response?.card || null, error: '' }))
        .catch(error => live && setState({ card: null, error: error?.message || 'Preview unavailable.' }));
    }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [transport, type, draft]);
  if (state.error) return <Text accessibilityRole="alert" style={[styles.error, { color: palette.danger }]}>{state.error}</Text>;
  if (!state.card) return <ActivityIndicator />;
  return <View style={styles.preview}>
    <MediaCard model={state.card} labels={previewLabels} palette={mediaCardPalette} width={160} readOnly />
  </View>;
}

const styles = StyleSheet.create({
  preview: { alignSelf: 'center', width: 160 },
  error: { fontSize: 12, lineHeight: 17 },
});

function CardsForm({ transport, payload }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const [model, setModel] = useState(() => cardsFromPayload(payload));
  const [values, setValues] = useState(model.values);
  const [savedValues, setSavedValues] = useState(model.values);

  async function save({ values: submitted }) {
    const response = await transport.saveCards(submitted);
    const next = cardsFromPayload(response);
    setModel(next);
    setValues(next.values);
    setSavedValues(next.values);
  }

  return <SettingsCardsView
    catalog={model.catalog}
    saved={values.saved}
    initialSaved={savedValues.saved}
    initialTouchActions={savedValues.touchActions}
    touchActions={values.touchActions}
    onChange={setValues}
    onSave={save}
    palette={settingsPalette}
    buttonPalette={buttonPalette}
    labels={{ footnote: 'Title language and book progress stay in Preferences.' }}
    renderPreview={({ type, saved }) => <CardPreview transport={transport} type={type} saved={saved} />}
  />;
}

export default function CardsSettingsSlot() {
  const resource = useSettingsResource(transport => transport.loadCards());
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <CardsForm transport={resource.transport} payload={resource.data} />;
}
