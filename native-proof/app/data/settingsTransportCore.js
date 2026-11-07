// Read/write helpers for the user settings endpoints the native screens can
// map without a server-rendered form. Other settings pages (appearance, cards,
// home rows, users, access tokens) do not have a JSON read endpoint yet.
const PREFERENCE_FIELDS = [
  'date_format',
  'time_format',
  'currency',
  'week_start_day',
  'activity_history_view',
  'duration_format',
  'game_logging_style',
  'mobile_grid_layout',
  'media_card_subtitle_display',
  'title_display_preference',
  'top_talent_sort_by',
  'rating_scale',
  'show_planned_on_home',
  'anime_library_mode',
  'quick_season_update_mobile',
  'session_duration',
  'hide_completed_recommendations',
  'hide_zero_rating',
  'progress_bar',
  'book_comic_manga_progress_percentage',
  'auto_pause_in_progress_enabled',
  'obfuscate_episodes',
  'clickable_media_cards',
  'home_show_media_type_headers',
];

export function preferencesToForm(payload) {
  const prefs = payload?.preferences || {};
  const values = {};
  PREFERENCE_FIELDS.forEach(field => {
    if (!(field in prefs)) return;
    if (field === 'session_duration') {
      values[field] = String(prefs[field]);
      return;
    }
    values[field] = prefs[field];
  });
  return values;
}

export function preferencesPatch(values) {
  const patch = {};
  PREFERENCE_FIELDS.forEach(field => {
    if (!(field in (values || {}))) return;
    if (field === 'session_duration') {
      const number = Number(values[field]);
      if (Number.isFinite(number)) patch[field] = number;
      return;
    }
    patch[field] = values[field];
  });
  return patch;
}

export function notificationsToForm(payload) {
  return {
    dailyDigestEnabled: Boolean(payload?.daily_digest_enabled),
    releaseNotificationsEnabled: Boolean(payload?.release_notifications_enabled),
    notificationUrlsConfigured: Boolean(payload?.notification_urls_configured),
  };
}

export function notificationPatchFromForm(values) {
  const patch = {
    daily_digest_enabled: Boolean(values?.dailyDigestEnabled),
    release_notifications_enabled: Boolean(values?.releaseNotificationsEnabled),
  };
  if (values?.notificationUrls) patch.notification_urls = values.notificationUrls;
  return patch;
}

export function createRemoteSettingsActions(request) {
  return {
    mode: 'server',
    loadPreferences() {
      return request('/api/v1/user/preferences/');
    },
    savePreferences(values) {
      return request('/api/v1/user/preferences/', {
        method: 'PATCH',
        body: preferencesPatch(values),
      });
    },
    savePlaybackWebhook(values) {
      return request('/api/v1/user/preferences/', {
        method: 'PATCH',
        body: values,
      });
    },
    loadNotifications() {
      return request('/api/v1/user/notifications/');
    },
    saveNotifications(values) {
      return request('/api/v1/user/notifications/', {
        method: 'PATCH',
        body: values,
      });
    },
    excludeNotificationItem({ itemId }) {
      return request('/api/v1/user/notifications/exclusions/', {
        method: 'POST',
        body: { item_id: itemId },
      });
    },
    searchNotificationItems({ search }) {
      return request('/api/v1/media/', { query: { search, limit: 20, offset: 0 } });
    },
    includeNotificationItem({ itemId }) {
      return request('/api/v1/user/notifications/exclusions/', {
        method: 'DELETE',
        body: { item_id: itemId },
      });
    },
    loadNotificationExclusions() {
      return request('/api/v1/user/notifications/exclusions/');
    },
    testNotification() {
      return request('/api/v1/user/notifications/test/', { method: 'POST', body: {} });
    },
  };
}

export function createLocalSettingsActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    loadPreferences: local,
    savePreferences: local,
    savePlaybackWebhook: local,
    loadNotifications: local,
    saveNotifications: local,
    excludeNotificationItem: local,
    includeNotificationItem: local,
    searchNotificationItems: local,
    loadNotificationExclusions: local,
    testNotification: local,
  };
}