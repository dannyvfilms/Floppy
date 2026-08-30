from django.urls import path

from users import onboarding_views, server_port_views, views

urlpatterns = [
    path("setup/", onboarding_views.onboarding_media_types, name="onboarding_media_types"),
    path(
        "setup/services/<int:index>/",
        onboarding_views.onboarding_services,
        name="onboarding_services",
    ),
    path(
        "setup/services/summary/",
        onboarding_views.onboarding_services_summary,
        name="onboarding_services_summary",
    ),
    path(
        "setup/connect/",
        onboarding_views.onboarding_service_setup,
        name="onboarding_service_setup",
    ),
    path(
        "setup/connect/<slug:slug>/skip/",
        onboarding_views.onboarding_skip_service,
        name="onboarding_skip_service",
    ),
    path(
        "setup/import-status/",
        onboarding_views.onboarding_import_status,
        name="onboarding_import_status",
    ),
    path(
        "setup/integrations/",
        onboarding_views.onboarding_integration_setup,
        name="onboarding_integration_setup",
    ),
    path(
        "setup/integrations/<slug:slug>/skip/",
        onboarding_views.onboarding_skip_integration,
        name="onboarding_skip_integration",
    ),
    path("setup/resume/", onboarding_views.onboarding_resume, name="onboarding_resume"),
    path("setup/restart/", onboarding_views.onboarding_restart, name="onboarding_restart"),
    path("accounts/password/recover/", views.password_recover, name="password_recover"),
    path("settings/account", views.account, name="account"),
    path("settings/notifications", views.notifications, name="notifications"),
    path("notifications/search/", views.search_items, name="search_notification_items"),
    path(
        "notifications/exclude/",
        views.exclude_item,
        name="exclude_notification_item",
    ),
    path(
        "notifications/include/",
        views.include_item,
        name="include_notification_item",
    ),
    path("test_notification", views.test_notification, name="test_notification"),
    path("settings/ui", views.ui_preferences, name="ui_preferences"),
    path("settings/appearance", views.appearance, name="appearance"),
    path("settings/sidebar", views.sidebar, name="sidebar"),
    path("settings/home-screen", views.home_screen, name="home_screen"),
    path(
        "settings/home-screen/lists",
        views.home_screen_list_search,
        name="home_screen_list_search",
    ),
    path(
        "settings/home-screen/filter-fields",
        views.home_screen_filter_fields,
        name="home_screen_filter_fields",
    ),
    path(
        "settings/home-screen/rows/<int:row_id>/toggle-direction",
        views.toggle_home_screen_row_direction,
        name="toggle_home_screen_row_direction",
    ),
    path(
        "settings/toggle-obfuscate-episodes",
        views.toggle_obfuscate_episodes,
        name="toggle_obfuscate_episodes",
    ),
    path("settings/preferences", views.preferences, name="preferences"),
    path("settings/integrations", views.integrations, name="integrations"),
    path("settings/rss", views.rss_settings, name="rss_settings"),
    path("settings/import", views.import_data, name="import_data"),
    path(
        "settings/import/save-settings",
        views.save_import_settings,
        name="save_import_settings",
    ),
    path(
        "settings/import/activity",
        views.import_data_activity,
        name="import_data_activity",
    ),
    path(
        "settings/import/plex-status",
        views.import_data_plex_status,
        name="import_data_plex_status",
    ),
    path(
        "settings/import/plex-sections",
        views.import_data_plex_sections,
        name="import_data_plex_sections",
    ),
    path("settings/export", views.export_data, name="export_data"),
    path("settings/advanced", views.advanced, name="advanced"),
    path(
        "settings/advanced/image-cache",
        views.update_image_cache,
        name="update_image_cache",
    ),
    path(
        "settings/advanced/image-cache/clear",
        views.clear_image_cache,
        name="clear_image_cache",
    ),
    path("settings/advanced/logs", views.export_logs, name="export_logs"),
    path(
        "settings/advanced/server-port",
        server_port_views.update_server_port,
        name="update_server_port",
    ),
    path("settings/about", views.about, name="about"),
    path(
        "delete_import_schedule",
        views.delete_import_schedule,
        name="delete_import_schedule",
    ),
    path(
        "rollback_import_run/<int:run_id>",
        views.rollback_import_run,
        name="rollback_import_run",
    ),
    path(
        "cancel_import_run/<int:run_id>",
        views.cancel_import_run,
        name="cancel_import_run",
    ),
    path(
        "bulk_delete_by_import_source/<str:media_type>/<str:source>",
        views.bulk_delete_by_import_source,
        name="bulk_delete_by_import_source",
    ),
    path(
        "bulk_delete_by_media_type",
        views.bulk_delete_by_media_type,
        name="bulk_delete_by_media_type",
    ),
    path(
        "create_export_schedule",
        views.create_export_schedule,
        name="create_export_schedule",
    ),
    path(
        "delete_export_schedule",
        views.delete_export_schedule,
        name="delete_export_schedule",
    ),
    path("regenerate_token", views.regenerate_token, name="regenerate_token"),
    path("clear_search_cache", views.clear_search_cache, name="clear_search_cache"),
    path(
        "clear_history_cache",
        views.clear_history_cache,
        name="clear_history_cache",
    ),
    path(
        "clear_statistics_cache",
        views.clear_statistics_cache,
        name="clear_statistics_cache",
    ),
    path(
        "clear_discover_cache",
        views.clear_discover_cache,
        name="clear_discover_cache",
    ),
    path("clear_all_caches", views.clear_all_caches, name="clear_all_caches"),
    path("update_tmdb_proxy", views.update_tmdb_proxy, name="update_tmdb_proxy"),
    path(
        "update_plex_usernames",
        views.update_plex_usernames,
        name="update_plex_usernames",
    ),
    path(
        "update_plex_webhook_libraries",
        views.update_plex_webhook_libraries,
        name="update_plex_webhook_libraries",
    ),
    path(
        "update_plex_webhook_share",
        views.update_plex_webhook_share,
        name="update_plex_webhook_share",
    ),
    path(
        "toggle_plex_webhook_share",
        views.toggle_plex_webhook_share,
        name="toggle_plex_webhook_share",
    ),
    path(
        "delete_plex_webhook_share",
        views.delete_plex_webhook_share,
        name="delete_plex_webhook_share",
    ),
    path(
        "update_jellyfin_webhook_events",
        views.update_jellyfin_webhook_events,
        name="update_jellyfin_webhook_events",
    ),
    # kept: URL path/name unchanged, matches views.py route (see plan)
    path(
        "settings/integrations/jellyseerr/",
        views.update_jellyseerr_settings,
        name="update_jellyseerr_settings",
    ),
]
