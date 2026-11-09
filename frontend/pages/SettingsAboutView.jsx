import React from 'react';
import { View } from 'react-native';
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
  copy: 'Version, release notes, resources, specifications and licences.',
};

// About page composition: update banner, overview, release notes, install,
// project resources, API specifications, attributions, licences and version.
export function SettingsAboutView({
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
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    {banner ? <ReleaseUpdateBanner {...banner} palette={palette} labels={labels} /> : null}
    <AboutOverviewCard {...overview} palette={palette} labels={labels} icons={icons} />
    <WhatsNewCard {...whatsNew} palette={palette} labels={labels} icons={icons} />
    <InstallCard {...install} palette={palette} buttonPalette={buttonPalette} labels={labels} icons={icons} />
    <ProjectResourcesCard {...resources} palette={palette} labels={labels} icons={icons} />
    <DeveloperSpecsCard {...specs} palette={palette} labels={labels} icons={icons} />
    <AttributionsCard {...attributions} palette={palette} labels={labels} icons={icons} />
    <LicenseCard {...licenses} palette={palette} labels={labels} icons={icons} />
    <AboutVersionFooter {...version} palette={palette} labels={labels} />
    </>}
  </SettingsPage></View>;
}
