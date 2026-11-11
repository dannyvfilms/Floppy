import React from 'react';
import { Text, View } from 'react-native';
import {
  AboutOverviewCard,
  AboutVersionFooter,
  AttributionsCard,
  DeveloperSpecsCard,
  InstallCard,
  LicenseCard,
  ProjectResourcesCard,
  ReleaseUpdateBanner,
  WhatsNewCard,
} from '../settings/AboutSettings';
import { SettingsPage } from './SettingsView';

export const settingsAboutCopy = {
  title: 'About',
  copy: '',
};

// About page composition: update banner, overview, release notes, install,
// project resources, API specifications, attributions, licences and version.
export function SettingsAboutView({
  presentation = {},
  banner = null,
  overview = {},
  whatsNew = {},
  install = {},
  resources = {},
  specs = {},
  attributions = {},
  licenses = {},
  version = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  labels = {},
  icons = {},
}) {
  const copy = { ...settingsAboutCopy, ...(labels || {}) };
  return <View style={palette.pageCards ? { padding: 24, backgroundColor: palette.surface, borderRadius: palette.radius ?? 8 } : undefined}>
    {palette.pageCards ? <Text role="heading" aria-level={2} style={{ fontSize: 24, lineHeight: 32, fontWeight: '700', color: palette.text, marginBottom: 24 }}>About Floppy</Text> : null}
    <SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    {banner ? <ReleaseUpdateBanner {...banner} palette={palette} labels={labels} /> : null}
    <AboutOverviewCard {...overview} palette={palette} labels={presentation.overview?.labels || labels} icons={presentation.overview?.icons || icons} />
    <WhatsNewCard {...whatsNew} palette={palette} labels={presentation.whatsNew?.labels || labels} icons={presentation.whatsNew?.icons || icons} />
    <InstallCard {...install} palette={palette} buttonPalette={buttonPalette} labels={presentation.install?.labels || labels} icons={presentation.install?.icons || icons} />
    <ProjectResourcesCard {...resources} palette={palette} labels={presentation.resources?.labels || labels} icons={presentation.resources?.icons || icons} />
    <DeveloperSpecsCard {...specs} palette={palette} labels={presentation.specs?.labels || labels} icons={presentation.specs?.icons || icons} />
    <AttributionsCard {...attributions} palette={palette} labels={presentation.attributions?.labels || labels} icons={presentation.attributions?.icons || icons} />
    <LicenseCard {...licenses} palette={palette} labels={presentation.licenses?.labels || labels} icons={presentation.licenses?.icons || icons} />
    <AboutVersionFooter {...version} palette={palette} labels={labels} />
    </>}
  </SettingsPage></View>;
}
