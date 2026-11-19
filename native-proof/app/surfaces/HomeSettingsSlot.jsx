import React, { useEffect, useState } from 'react';
import { SettingsHomeView } from '../../../frontend/pages/SettingsHomeScreenView';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { homeFromPayload } from '../data/settingsTransport';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

export const surface = {
  id: 'SET-HOME',
  title: 'Home screen row editor',
  where: 'Settings home screen sections, rows, filters, sorts and chips',
  status: 'in_progress',
  note: 'Sections, rows, sort choices, headers and media-type chips load from /api/v1/user/home-screen/ and save through PUT on the same route, which validates with save_home_screen_configuration like the web form. List suggestions load from /api/v1/user/home-screen/lists/ and each section\'s filter fields are fetched in the background from /filter-fields/ (the web page fetches them when a section opens). Browser and device runtime interaction were not exercised.',
};

function withFilterFields(sections, mediaType, fields) {
  return sections.map(section => (section.media_type === mediaType
    ? { ...section, filter_fields: fields }
    : section));
}

function HomeForm({ transport, payload, listChoices }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const [model, setModel] = useState(() => homeFromPayload(payload));
  const [values, setValues] = useState(model.values);
  const [savedValues, setSavedValues] = useState(model.values);

  useEffect(() => {
    let active = true;
    (async () => {
      for (const section of model.sections) {
        if (!active) return;
        try {
          const response = await transport.loadHomeFilterFields({ mediaType: section.media_type });
          if (!active) return;
          const fields = response?.filter_fields || [];
          setValues(current => ({ ...current, sections: withFilterFields(current.sections, section.media_type, fields) }));
          setSavedValues(current => ({ ...current, sections: withFilterFields(current.sections, section.media_type, fields) }));
        } catch {
          // A section without filter fields still edits its other row options.
        }
      }
    })();
    return () => { active = false; };
  }, [model, transport]);

  async function save({ values: submitted }) {
    const response = await transport.saveHomeScreen(submitted);
    const next = homeFromPayload(response);
    setModel(next);
    setValues(next.values);
    setSavedValues(next.values);
  }

  return <SettingsHomeView
    dragIcon={actionIcons.grip}
    heading={false}
    sections={values.sections}
    initialSections={savedValues.sections}
    listChoices={listChoices}
    mediaTypeChipStyles={model.mediaTypeChipStyles}
    showMediaTypeHeaders={values.showMediaTypeHeaders}
    mediaTypeChipsEnabled={values.mediaTypeChipsEnabled}
    mediaTypeChipStyle={values.mediaTypeChipStyle}
    onChange={setValues}
    onSave={save}
    palette={{ ...settingsPalette, pageCards: true }}
    labels={{ copy: 'These groups are the rows on the home screen. Drag to reorder, click to edit.' }}
    buttonPalette={buttonPalette}
  />;
}

export default function HomeSettingsSlot() {
  const resource = useSettingsResource(async transport => {
    const [payload, lists] = await Promise.all([
      transport.loadHomeScreen(),
      transport.searchHomeLists({ q: '', mediaType: '' }).catch(() => ({ results: [] })),
    ]);
    return { payload, listChoices: lists?.results || [] };
  });
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <HomeForm transport={resource.transport} payload={resource.data.payload}
    listChoices={resource.data.listChoices} />;
}
