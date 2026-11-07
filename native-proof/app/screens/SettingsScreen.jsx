import React, { useEffect, useState } from 'react';
import { SettingsView } from '../../../frontend/pages/SettingsView';
import { Screen } from '../components/Screen';
import AppearanceSettingsSlot from '../surfaces/AppearanceSettingsSlot';
import CardsSettingsSlot from '../surfaces/CardsSettingsSlot';
import DataAccessNotificationsSlot from '../surfaces/DataAccessNotificationsSlot';
import HomeSettingsSlot from '../surfaces/HomeSettingsSlot';
import PreferencesSlot from '../surfaces/PreferencesSlot';
import UsersSlot from '../surfaces/UsersSlot';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { palette } from '../theme';

// Real settings navigation shared with the web page. The settings tab no longer
// lists demo screens: each entry opens the same page composition the browser
// uses. Routes without a native adapter (providers directory/activity, sidebar
// media ordering) are marked server-only by the shared navigation model instead
// of showing a native-only fake.
const INLINE_PAGES = {
  settingsPreferences: PreferencesSlot,
  settingsAppearance: AppearanceSettingsSlot,
  settingsCards: CardsSettingsSlot,
  settingsHome: HomeSettingsSlot,
  settingsUsers: UsersSlot,
  settingsData: DataAccessNotificationsSlot,
  settingsAccess: DataAccessNotificationsSlot,
  settingsNotifications: DataAccessNotificationsSlot,
};

const DATA_PAGE_KIND = {
  settingsData: 'data',
  settingsAccess: 'access',
  settingsNotifications: 'notifications',
};

function isSuperuser(session) {
  const user = session?.user;
  return Boolean(user?.isSuperuser || user?.is_superuser);
}

export default function SettingsScreen({ navigate }) {
  const [active, setActive] = useState('settingsPreferences');
  const [superuser, setSuperuser] = useState(() => isSuperuser(getActiveAuthSession()));

  useEffect(() => subscribeAuthSession(session => setSuperuser(isSuperuser(session))), []);

  function selectPage(item) {
    if (item.page === 'settingsAccount') {
      navigate('Auth');
      return;
    }
    if (item.page === 'settingsAdvanced' || item.page === 'settingsAbout') {
      navigate('SettingsAdvanced', { page: item.page === 'settingsAbout' ? 'about' : 'advanced' });
      return;
    }
    if (INLINE_PAGES[item.page]) setActive(item.page);
  }

  const Page = INLINE_PAGES[active];
  const pageKind = DATA_PAGE_KIND[active];
  const content = Page
    ? pageKind ? <Page page={pageKind} /> : <Page />
    : null;

  return <Screen chrome={false}>
    <SettingsView active={active} onNavigate={selectPage}
      permissions={{ superuser }} palette={palette}>
      {content}
    </SettingsView>
  </Screen>;
}
