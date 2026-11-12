import React from 'react';
import AccessSettingsSlot from './AccessSettingsSlot';
import DataSettingsSlot from './DataSettingsSlot';
import NotificationsSettingsSlot from './NotificationsSettingsSlot';

export const surface = {
  id: 'SET-DATA',
  title: 'Data, access and notification settings',
  where: 'Settings data export, RSS, access tokens, OAuth grants and notifications',
  status: 'in_progress',
  note: 'Dispatches to three slots that read and write real endpoints. Data: /api/v1/exports/schedules/, /exports/history/, /export/csv/, /user/restore/, /user/rss/ (+ preview), /user/library-maintenance/. Access: /user/token/, /user/tokens/, /user/catalog-grants/, /user/oauth-applications/. Notifications: /user/notifications/ including the premiere toggle and playback webhook. File flows (CSV save, backup pick) go through data/fileFlows with a web variant; clipboard copy uses the share sheet on native. Runtime interaction in a browser, iOS or Android was not exercised.',
};

const SLOTS = {
  data: DataSettingsSlot,
  rss: DataSettingsSlot,
  access: AccessSettingsSlot,
  applications: AccessSettingsSlot,
  notifications: NotificationsSettingsSlot,
};

export default function DataAccessNotificationsSlot({ page = 'data', onNavigate, onOpenRss, onOpenApplications }) {
  const Slot = SLOTS[page] || DataSettingsSlot;
  return <Slot page={page} onNavigate={onNavigate} onOpenRss={onOpenRss} onOpenApplications={onOpenApplications} />;
}
