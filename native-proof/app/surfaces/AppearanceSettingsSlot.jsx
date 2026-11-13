import React, { useState } from 'react';
import { SettingsAppearanceView } from '../../../frontend/pages/SettingsAppearanceView';
import { appearanceFromPayload } from '../data/settingsTransport';
import { applyServerTheme } from '../themeSync';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';
import SettingsSaveBar from './SettingsSaveBar';
import { themeSwatches } from '../theme';
import { settingsNavIcons } from '../settingsNavIcons';

export const surface = {
  id: 'SET-APPEARANCE',
  title: 'Appearance and detail layout editor',
  where: 'Settings appearance theme, custom palette and detail section layout',
  status: 'in_progress',
  note: 'Presets, palette definitions, effect ranges and every detail-layout family load from /api/v1/user/appearance/ and save through PUT on the same route, which validates the whole payload before saving any part. Custom surface and panel opacity is applied through colour tokens, and render-time radius consumers receive the chosen radius. Module-level static styles retain their initial radius. Backdrop blur is not implemented: React Native filter blur affects children and is not a backdrop effect, and no native backdrop-blur dependency is installed. Browser and device runtime interaction were not exercised.',
};

function AppearanceForm({ transport, payload }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const [model, setModel] = useState(() => appearanceFromPayload(payload));
  const [values, setValues] = useState(model.values);
  const [savedValues, setSavedValues] = useState(model.values);

  async function save({ values: submitted }) {
    const response = await transport.saveAppearance(submitted);
    const next = appearanceFromPayload(response);
    setModel(next);
    setValues(next.values);
    setSavedValues(next.values);
    applyServerTheme({ theme: next.values.theme, palette: next.values.palette });
  }

  return <SettingsAppearanceView
    swatches={themeSwatches} themeIcon={settingsNavIcons.sun}
    SaveBar={SettingsSaveBar}
    heading={false}
    presets={model.presets}
    colors={model.colors}
    effects={model.effects}
    families={model.families}
    values={values}
    initialValues={savedValues}
    onChange={setValues}
    onSave={save}
    palette={{ ...settingsPalette, pageCards: true }}
    buttonPalette={{ ...buttonPalette, primary: { ...buttonPalette.primary, background: settingsPalette.accent, text: settingsPalette.accentText } }}
  />;
}

export default function AppearanceSettingsSlot() {
  const resource = useSettingsResource(transport => transport.loadAppearance());
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <AppearanceForm transport={resource.transport} payload={resource.data} />;
}
