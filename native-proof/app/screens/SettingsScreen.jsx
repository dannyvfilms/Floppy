import React, { useEffect, useState } from 'react';
import { SettingsView } from '../../../frontend/pages/SettingsView';
import { Icon } from '../../../frontend/ui/Icon';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { Screen } from '../components/Screen';
import AboutSettingsSlot from '../surfaces/AboutSettingsSlot';
import ActivitySettingsSlot from '../surfaces/ActivitySettingsSlot';
import AdvancedSettingsSlot from '../surfaces/AdvancedSettingsSlot';
import AppearanceSettingsSlot from '../surfaces/AppearanceSettingsSlot';
import CardsSettingsSlot from '../surfaces/CardsSettingsSlot';
import DataAccessNotificationsSlot from '../surfaces/DataAccessNotificationsSlot';
import HomeSettingsSlot from '../surfaces/HomeSettingsSlot';
import PreferencesSlot from '../surfaces/PreferencesSlot';
import SidebarSettingsSlot from '../surfaces/SidebarSettingsSlot';
import UsersSlot from '../surfaces/UsersSlot';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { createSettingsTransport } from '../data/settingsTransport';
import { palette, spacing } from '../theme';
import { settingsNavIcons } from '../settingsNavIcons';
import { useSettingsPalettes } from '../surfaces/settingsPalettes';
import { SettingsSaveBarHost } from '../surfaces/SettingsSaveBar';
import AuthScreen from './AuthScreen';

// Real settings navigation shared with the web page. Every entry opens the same
// page composition the browser uses. Account keeps its own screen (AuthScreen);
// Providers opens its own screen.
const INLINE_PAGES = {
  settingsAccount: AuthScreen,
  settingsPreferences: PreferencesSlot,
  settingsAppearance: AppearanceSettingsSlot,
  settingsCards: CardsSettingsSlot,
  settingsSidebar: SidebarSettingsSlot,
  providerActivity: ActivitySettingsSlot,
  settingsHome: HomeSettingsSlot,
  settingsUsers: UsersSlot,
  settingsData: DataAccessNotificationsSlot,
  settingsRss: DataAccessNotificationsSlot,
  settingsAccess: DataAccessNotificationsSlot,
  settingsApplications: DataAccessNotificationsSlot,
  settingsNotifications: DataAccessNotificationsSlot,
  settingsAdvanced: AdvancedSettingsSlot,
  settingsAbout: AboutSettingsSlot,
};

const AVAILABLE_PAGES = ['providers', ...Object.keys(INLINE_PAGES)];

const DATA_PAGE_KIND = {
  settingsData: 'data',
  settingsRss: 'rss',
  settingsAccess: 'access',
  settingsApplications: 'applications',
  settingsNotifications: 'notifications',
};

// The server decides: is_superuser comes from /api/v1/user/preferences/, the
// same account the settings pages act for. The Users page re-checks on the
// server, so a wrong guess here can only hide a link, never grant access.
function useSuperuser() {
  const [superuser, setSuperuser] = useState(false);
  useEffect(() => {
    let active = true;
    function check(session) {
      if (!session || typeof session.request !== 'function') {
        setSuperuser(false);
        return;
      }
      createSettingsTransport({ auth: session }).loadPreferences()
        .then(payload => { if (active) setSuperuser(Boolean(payload?.is_superuser)); })
        .catch(() => { if (active) setSuperuser(false); });
    }
    check(getActiveAuthSession());
    const off = subscribeAuthSession(check);
    return () => { active = false; off(); };
  }, []);
  return superuser;
}

export function SettingsSurface({ children, navigate, active = 'providers', onNavigate }) {
  const superuser = useSuperuser();
  const { settingsPalette } = useSettingsPalettes();

  const selectPage = onNavigate || (item => navigate(item.page === 'providers' ? 'Providers' : 'Settings', { page: item.page }));
  return <SettingsSaveBarHost><Screen key={active} chrome={false} contentStyle={{ paddingTop: spacing.xl + 1, paddingBottom: 160 }}>
    <SettingsView active={active === 'settingsRss' ? 'settingsData' : active === 'settingsApplications' ? 'settingsAccess' : active} onNavigate={selectPage}
      permissions={{ superuser }} availablePages={AVAILABLE_PAGES} palette={settingsPalette}
      icons={{ chevron: actionIcons.chevronDown }}
      renderIcon={name => (settingsNavIcons[name]
        ? <Icon spec={settingsNavIcons[name]} color={palette.textMuted} size={16} />
        : null)}>
      {children}
    </SettingsView>
  </Screen></SettingsSaveBarHost>;
}

export default function SettingsScreen({ navigate, params }) {
  const [active, setActive] = useState(() => INLINE_PAGES[params?.page] ? params.page : 'settingsPreferences');
  useEffect(() => {
    if (INLINE_PAGES[params?.page]) setActive(params.page);
  }, [params?.page]);

  function selectPage(item) {
    if (item.page === 'providers') {
      navigate('Providers');
      return;
    }
    if (INLINE_PAGES[item.page]) setActive(item.page);
  }

  const Page = INLINE_PAGES[active];
  const pageKind = DATA_PAGE_KIND[active];
  const content = Page
    ? active === 'settingsAccount' ? <Page embedded />
      : pageKind ? <Page key={active} page={pageKind} onNavigate={navigate} onOpenRss={() => setActive('settingsRss')} onOpenApplications={() => setActive('settingsApplications')} /> : <Page onNavigate={navigate} onOpenCards={() => setActive('settingsCards')} />
    : null;

  return <SettingsSurface navigate={navigate} active={active} onNavigate={selectPage}>{content}</SettingsSurface>;
}
