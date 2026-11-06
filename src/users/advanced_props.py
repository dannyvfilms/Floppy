"""Build the shared Advanced and About card props for the browser adapters."""

from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils import formats
from django.utils.translation import gettext as _

from app.icon_specs import file_icon
from users import release_notes
from users.server_port_views import server_port_context

GITHUB_ISSUE_URL = "https://github.com/dannyvfilms/Floppy/issues/new"
INSTALL_GUIDE_URL = (
    "https://github.com/dannyvfilms/Floppy/wiki/"
    "2.-User-Guide#installing-floppy-on-your-phone"
)


def _advanced_labels() -> dict[str, object]:
    """Return the translated Advanced card copy."""
    return {
        "logs": {
            "title": _("Logs & Bug Reports"),
            "intro": _(
                "Logs may contain private activity. Administrators can download "
                "redacted logs and should review them before sharing."
            ),
            "covers": _("Covers {when} onward."),
            "lastUnclean": _("Last unclean shutdown: {when}"),
            "download": _("Download Sanitized Logs"),
            "bugReport": _("File a Bug Report"),
        },
        "imageCache": {
            "title": _("External Image Caching"),
            "intro": _(
                "Proxy artwork from approved metadata providers through Floppy so "
                "browsers and API clients do not need direct access to those "
                "providers. Cached images use disk space and are removed "
                "automatically after 30 days without access."
            ),
            "cachedImages": _("Cached images"),
            "diskUsage": _("Disk usage"),
            "hosts": _(
                "Only known provider image hosts are cached (including TMDB, TVDB, "
                "MyAnimeList, IGDB, Open Library, Hardcover, ComicVine, "
                "BoardGameGeek, MusicBrainz, Pocket Casts, iTunes, Kitsu, and "
                "AniList). Manual URLs, local services, placeholders, and unknown "
                "hosts stay unchanged."
            ),
            "toggleLabel": _("Enable external image caching"),
            "disabled": _("Disabled"),
            "enabled": _("Enabled"),
            "save": _("Save"),
            "clear": _("Clear Image Cache"),
            "confirmTitle": _("Clear Image Cache?"),
            "confirmMessage": _(
                "Clear all cached external images? They will be downloaded again "
                "if caching remains enabled."
            ),
            "confirmWarning": _(
                "Artwork may briefly reload the next time it is requested."
            ),
            "confirmLabel": _("Clear Image Cache"),
            "clearError": _("Could not clear the image cache."),
            "saveError": _("Could not update image caching."),
            "superuserOnly": _(
                "Only a superuser can change this setting or clear the cache."
            ),
            "status": _("Status:"),
        },
        "cache": {
            "title": _("Cache Management"),
            "intro": _(
                "Floppy caches computed pages (History, Statistics, Discover) and "
                "provider search results so they load fast. If one looks stale or "
                "wrong, clearing it forces a rebuild from your actual data — "
                "nothing about your library, watch history, ratings, or lists is "
                "touched by any of these."
            ),
            "clear": _("Clear"),
            "clearAll": _("Clear All Caches"),
            "clearing": _("{kind} cache is clearing…"),
            "confirmError": _("Could not clear that cache."),
            "rows": [
                {
                    "key": "search",
                    "title": _("Search Cache"),
                    "description": _(
                        "Provider search results — shared instance-wide"
                    ),
                },
                {
                    "key": "history",
                    "title": _("History Cache"),
                    "description": _("Your cached History page — just you"),
                },
                {
                    "key": "statistics",
                    "title": _("Statistics Cache"),
                    "description": _("Your cached Statistics page — just you"),
                },
                {
                    "key": "discover",
                    "title": _("Discover Cache"),
                    "description": _(
                        "Your recommendation rows & taste profile — just you"
                    ),
                },
            ],
            "confirms": {
                "search": {
                    "title": _("Clear Search Cache?"),
                    "message": _(
                        "This is the one shared cache here — clearing it affects "
                        "every user on this Floppy instance, not just you."
                    ),
                    "warning": _(
                        "No data is lost. The next search anyone makes will be a "
                        "bit slower while it re-fetches from TMDB, TVDB, and the "
                        "other providers."
                    ),
                    "confirmLabel": _("Clear Search Cache"),
                },
                "history": {
                    "title": _("Clear History Cache?"),
                    "message": _(
                        "Only affects your own account. Your watch history itself "
                        "is not touched — this only clears the cached, day-by-day "
                        "rendering of it."
                    ),
                    "warning": _(
                        "The History page will rebuild itself the next time you "
                        "open it, which may take a moment the first time."
                    ),
                    "confirmLabel": _("Clear History Cache"),
                },
                "statistics": {
                    "title": _("Clear Statistics Cache?"),
                    "message": _(
                        "Only affects your own account. No underlying data is "
                        "touched — only the cached charts and totals."
                    ),
                    "warning": _(
                        "Statistics rebuild in the background rather than on your "
                        "next page load — expect placeholder values for a bit "
                        "until that finishes."
                    ),
                    "confirmLabel": _("Clear Statistics Cache"),
                },
                "discover": {
                    "title": _("Clear Discover Cache?"),
                    "message": _(
                        "Only affects your own account. Your recommendation rows "
                        "and taste profile get recomputed from scratch."
                    ),
                    "warning": _(
                        "Rows may look different or take a moment to repopulate. "
                        "Shared provider data other users draw on is not affected."
                    ),
                    "confirmLabel": _("Clear Discover Cache"),
                },
                "all": {
                    "title": _("Clear All Caches?"),
                    "message": _(
                        "This runs all four clears at once: Search (instance-wide) "
                        "plus your History, Statistics, and Discover caches."
                    ),
                    "warning": _(
                        "Search results go stale for every user until re-fetched. "
                        "History and Discover rebuild as you browse, and Statistics "
                        "shows placeholders until a background task finishes. No "
                        "watch history, ratings, lists, or tracked media is deleted."
                    ),
                    "confirmLabel": _("Clear All Caches"),
                },
            },
        },
    }


def _server_port_labels(can_manage: bool) -> dict[str, object]:
    """Return the translated server-port copy for the active account."""
    labels: dict[str, object] = {
        "title": _("Server port"),
        "introReadOnly": _(
            "This status is read-only for your account. An instance administrator "
            "can change the saved listener."
        ),
        "runningListener": _("Running listener"),
        "configuredPort": _("Configured port"),
        "savedFallback": _("Saved fallback"),
        "notReported": _("Not reported"),
        "unavailable": _("Unavailable"),
        "runningHelp": _(
            "Listener reported by the current packaged launcher."
        ),
        "configuredHelp": _("Source: {source}"),
        "configuredUnavailable": _(
            "Correct the active configuration before restart."
        ),
        "unreadable": _("Unreadable"),
        "notEvaluated": _("Not evaluated"),
        "unreadableHelp": _(
            "Repair or reset the saved value before it can be used."
        ),
        "notEvaluatedHelp": _(
            "Correct the environment value before evaluating fallbacks."
        ),
        "storedHelp": _("Stored under the Floppy data directory."),
        "defaultHelp": _("No saved override. The default is {port}."),
        "configAdminTitle": _(
            "Server port configuration needs administrator attention"
        ),
        "configAdminBody": _(
            "Detailed configuration errors and recovery controls are hidden for "
            "this account."
        ),
        "notesTitle": _("Deployment notes"),
        "notes": [
            _(
                "• For a normal host-port change, keep Floppy on 8000 and map "
                "another host port, for example 9000:8000."
            ),
            _(
                "• If the internal listener must move, use the same target in the "
                "container mapping, for example 9000:9000."
            ),
            _(
                "• If Floppy shares another container's network namespace, "
                "publish the selected port on the container that owns that "
                "namespace."
            ),
            _(
                "• The private application hop remains internal and is not changed "
                "by this setting."
            ),
        ],
    }
    if not can_manage:
        return labels
    labels.update({
        "introManage": _(
            "Change the public HTTP port only when another process in the same "
            "network namespace already uses port 8000. A normal Docker host-port "
            "change does not need this setting."
        ),
        "environmentTitle": _("Environment override is active"),
        "environmentBody": _(
            "controls this instance. This form cannot replace it. Change or remove "
            "the environment variable, then restart Floppy."
        ),
        "configEnvironmentTitle": _("Environment server port is invalid"),
        "configSavedTitle": _("Saved server port cannot be read"),
        "configEnvironmentHelp": _(
            "Correct {name} before you restart Floppy."
        ),
        "configSavedHelp": _(
            "Reset the saved value below, or correct the file before you restart "
            "Floppy."
        ),
        "formTitle": _("Internal listener"),
        "formHelp": _(
            "Use an integer from 1 through 65535. Saving changes the next listener "
            "value. It does not restart Floppy."
        ),
        "portLabel": _("Port"),
        "portHelp": _(
            "Priority: {name}, then the saved value, then {port}."
        ),
        "save": _("Save port"),
        "reset": _("Reset saved value"),
        "invalidPort": _("Use an integer from 1 through 65535."),
        "readOnlyNote": _(
            "Need to change the internal listener? Ask an instance administrator, "
            "or use the documented environment or CLI configuration for the host."
        ),
    })
    return labels


def advanced_props(request, context: dict[str, object]) -> dict[str, object]:
    """Return the browser Advanced cards' data and server action URLs."""
    last_unclean = context.get("last_unclean_exit")
    return {
        "csrfToken": get_token(request),
        "isSuperuser": request.user.is_superuser,
        "logsSince": context.get("logs_since") or "",
        "lastUncleanExit": (
            formats.date_format(last_unclean, "DATETIME_FORMAT")
            if last_unclean
            else ""
        ),
        "bugReportUrl": _bug_report_url(context),
        "imageEnabled": bool(context.get("image_caching_enabled")),
        "imageCount": (context.get("image_cache_stats") or {}).get("count", 0),
        "imageSize": context.get("image_cache_size") or "0 B",
        "labels": _advanced_labels(),
        "icons": {
            "logs": file_icon("vertical-sliders"),
            "image": file_icon("image"),
            "trash": file_icon("trashcan"),
            "warning": file_icon("warning"),
        },
        "urls": _advanced_urls(request.user.is_superuser),
    }


def _advanced_urls(is_superuser: bool) -> dict[str, object]:
    """Return only the action URLs the account can actually reach."""
    urls: dict[str, object] = {
        "clearCaches": {
            "search": reverse("clear_search_cache"),
            "history": reverse("clear_history_cache"),
            "statistics": reverse("clear_statistics_cache"),
            "discover": reverse("clear_discover_cache"),
            "all": reverse("clear_all_caches"),
        },
    }
    if is_superuser:
        urls.update({
            "logs": reverse("export_logs"),
            "updateImageCache": reverse("update_image_cache"),
            "clearImageCache": reverse("clear_image_cache"),
        })
    return urls


def server_port_props(request) -> dict[str, object]:
    """Return the server-port card state without leaking admin-only errors."""
    can_manage = request.user.is_superuser
    status = server_port_context()
    port_status = status["server_port_status"]
    config_error = status["server_port_config_error"] or ""
    config_source = status["server_port_config_error_source"] or ""
    labels = _server_port_labels(can_manage)
    if can_manage and not status["show_reset"]:
        labels.pop("reset", None)
    return {
        "csrfToken": get_token(request),
        "canManage": can_manage,
        "runtimePort": status["runtime_port"],
        "configuredPort": (
            getattr(port_status, "effective_port", None) if port_status else None
        ),
        "configuredSource": (
            getattr(port_status, "source", "") if port_status else ""
        ),
        "savedPort": (
            getattr(port_status, "saved_port", None) if port_status else None
        ),
        "defaultPort": status["default_port"],
        "savedFallbackUnreadable": config_source == "saved",
        "environmentOverride": status["environment_override"],
        "environmentName": status["environment_name"],
        "configError": config_error if can_manage else "",
        "configErrorPresent": bool(config_error),
        "configErrorSource": config_source if can_manage else "",
        "showReset": status["show_reset"],
        "labels": labels,
        "icons": {"server": file_icon("server")},
        "urls": (
            {"update": reverse("update_server_port")} if can_manage else {}
        ),
    }


def _bug_report_url(context: dict[str, object]) -> str:
    query = urlencode({
        "title": context.get("bug_report_title") or "[BUG] ",
        "body": context.get("bug_report_body") or "",
    })
    return f"{GITHUB_ISSUE_URL}?{query}"


def _about_labels() -> dict[str, object]:
    """Return the translated About card copy."""
    return {
        "overview": {
            "title": _("Description"),
            "description": _(
                "Floppy is an open-source, self-hosted media tracker and personal "
                "diary. Track, rate, and organize movies, shows, video games, "
                "books, music, podcasts, anime, comics, and more in one unified "
                "library."
            ),
            "support": _("Floppy is free and supported by"),
            "supportLink": _("users like you"),
        },
        "whatsNew": {
            "title": _("What's new"),
            "empty": _("Release notes could not be loaded from GitHub."),
            "loading": _("Loading release notes…"),
            "noHighlights": _("See the release page for what changed."),
            "releasePage": _("Release page on GitHub"),
            "allReleases": _("All releases on GitHub"),
            "installed": _("Installed"),
            "newer": _("Newer than yours"),
            "releaseNotes": _("{tag} release notes"),
            "releasePageLabel": _("{tag} release page on GitHub"),
        },
        "install": {
            "title": _("Install Floppy"),
            "intro": _(
                "Floppy is an installable PWA. Add it to your Home Screen to "
                "launch it like an app directly from your browser."
            ),
            "install": _("Install Floppy"),
            "iosTitle": _("iOS and iPadOS"),
            "iosSteps": [
                _("Open this instance in Safari."),
                _("Tap the Share button."),
                _("Choose Add to Home Screen."),
                _("Turn on Open as Web App if it is shown, then tap Add."),
            ],
            "androidTitle": _("Android"),
            "androidSteps": [
                _("Open this instance in Chrome."),
                _("Open the browser menu."),
                _("Choose Add to Home screen."),
                _(
                    "Confirm with Install, following your browser's wording."
                ),
            ],
            "guidePrefix": _("Installing on a phone instead? The"),
            "guideLink": _("installation guide"),
            "guideSuffix": _("has the iOS and Android steps."),
            "noControl": _(
                "No install control anywhere? Serve the instance over HTTPS and "
                "open it in a full browser rather than an in-app one. Tracking "
                "still needs a connection to your Floppy server."
            ),
            "guideLabel": _("Installation guide"),
            "installedStatus": _(
                "Installing Floppy. Look for it alongside your other apps."
            ),
            "dismissedStatus": _(
                "Installation dismissed. You can still add Floppy using the steps "
                "below."
            ),
            "failedStatus": _(
                "Your browser could not open the install prompt. Use the steps "
                "below instead."
            ),
        },
        "cache": {
            "title": _("Static cache"),
            "badge": _("Web only"),
            "description": _(
                "Service workers and the static cache belong to the browser "
                "app. They keep static assets available when the network is "
                "slow; tracking data still needs your Floppy server."
            ),
            "unavailable": _(
                "The service worker status could not be read in this browser."
            ),
            "unsupportedBrowser": _(
                "This browser does not support service workers."
            ),
            "unsupportedNative": _(
                "Not available in the native app. Native builds update through "
                "the app distribution channel."
            ),
            "refreshLabel": _("Check status"),
            "labels": {
                "registration": _("Service worker"),
                "active": _("Active worker"),
                "controlled": _("Page controlled"),
                "scope": _("Scope"),
                "caches": _("Static caches"),
            },
            "values": {
                "registered": _("Registered"),
                "notRegistered": _("Not registered"),
                "active": _("Running"),
                "inactive": _("Not running"),
                "controlled": _("Yes"),
                "uncontrolled": _("No"),
                "unsupported": _("Unsupported"),
                "none": _("None"),
            },
        },
        "resources": {"title": _("Project Resources"), "open": _("Open")},
        "specs": {
            "title": _("Developer & API Specifications"),
            "description": _(
                "Reviewed contracts and live schemas served by this instance."
            ),
            "formatSeparator": _(" · "),
            "open": _("Open"),
            "preview": _("Preview"),
            "download": _("Download"),
            "previewLabel": _("Preview {label}"),
            "downloadLabel": _("Download {label}"),
        },
        "attributions": {"title": _("Metadata & Attributions"), "open": _("Open")},
        "licenses": {"title": _("License & Legal"), "open": _("Open")},
        "version": {
            "version": _("Version:"),
            "commit": _("Commit:"),
            "unavailable": _("Unavailable"),
        },
    }


def about_props(request) -> dict[str, object]:
    """Return the browser About cards' data and external links."""
    labels = _about_labels()
    cached = cache.get(release_notes.CACHE_KEY)
    releases = cached or None
    installed = release_notes.release_tag(settings.VERSION)
    if releases:
        for release in releases:
            release["installed"] = release["tag"] == installed
            release["newer"] = release_notes.tag_sort_key(
                release["tag"],
            ) > release_notes.tag_sort_key(installed)
    return {
        "labels": labels,
        "overview": {
            "kind": "overview",
            "labels": labels["overview"],
            "icons": {"info": file_icon("info")},
            "sponsorUrl": (
                "https://github.com/sponsors/dannyvfilms"
                "?metadata_source=app-about-description"
            ),
        },
        "whatsNew": {
            "kind": "whatsNew",
            "labels": labels["whatsNew"],
            "icons": {"info": file_icon("info")},
            "releases": releases,
            "releasesLoaded": cached is not None,
            "releasesUrl": release_notes.RELEASES_PAGE_URL,
            "url": reverse("whats_new") + "?format=json",
        },
        "install": {
            "kind": "install",
            "labels": labels["install"],
            "icons": {"download": file_icon("download")},
            "guideUrl": INSTALL_GUIDE_URL,
        },
        "cache": {
            "kind": "cache",
            "labels": labels["cache"],
            "icons": {"server": file_icon("server")},
        },
        "resources": {
            "kind": "resources",
            "labels": labels["resources"],
            "icons": {
                "externalLink": file_icon("external-link"),
                "globe": file_icon("globe"),
                "github": file_icon("github"),
                "bookOpen": file_icon("book-open"),
                "bug": file_icon("bug"),
                "persons": file_icon("persons"),
                "heart": file_icon("heart"),
            },
            "items": [
                {
                    "label": _("Project Website"),
                    "description": _(
                        "Official documentation, guides, and live release "
                        "announcements"
                    ),
                    "url": "https://dannyvfilms.github.io/floppy/",
                },
                {
                    "label": _("Source Code"),
                    "description": _(
                        "GitHub repository, issue tracker, pull requests, and "
                        "releases"
                    ),
                    "url": "https://github.com/dannyvfilms/Floppy",
                },
                {
                    "label": _("Documentation"),
                    "description": _(
                        "Community wiki, container deployment, reverse proxy "
                        "setup, and guides"
                    ),
                    "url": "https://github.com/dannyvfilms/Floppy/wiki",
                },
                {
                    "label": _("Bug Reports"),
                    "description": _(
                        "Report bugs, submit sanitized logs, and request new "
                        "features"
                    ),
                    "url": "https://github.com/dannyvfilms/Floppy/issues",
                },
                {
                    "label": _("Community Discord"),
                    "description": _(
                        "Connect with other Floppy users, share setups, and help "
                        "each other out"
                    ),
                    "url": "https://discord.gg/uFgha7Kb6n",
                },
                {
                    "label": _("Support Floppy"),
                    "description": _(
                        "Floppy is free and open source, with no paid features. "
                        "If it has earned a place in your routine, sponsoring "
                        "helps it keep improving for everyone."
                    ),
                    "url": (
                        "https://github.com/sponsors/dannyvfilms"
                        "?metadata_source=app-about"
                    ),
                },
            ],
        },
        "specs": {
            "kind": "specs",
            "labels": labels["specs"],
            "icons": {
                "page": file_icon("page"),
                "bookOpen": file_icon("book-open"),
                "download": file_icon("download"),
            },
            "items": [
                {
                    "label": _("API Reference"),
                    "format": _("HTML Docs"),
                    "description": _(
                        "Interactive index, tasks, authentication recipes, and "
                        "curl cheat sheets"
                    ),
                    "url": reverse("swagger-ui"),
                },
                {
                    "label": _("Verified API Schema"),
                    "format": _("OpenAPI 3.0.3 (YAML)"),
                    "badge": "YAML",
                    "previewTitle": _(
                        "Verified API Schema (OpenAPI 3.0.3)"
                    ),
                    "description": _(
                        "Reviewed 41-operation subset for stable integrations "
                        "and MCP grounding"
                    ),
                    "url": reverse("openapi-contract"),
                    "downloadName": "openapi.yaml",
                },
                {
                    "label": _("Domain Context (JSON-LD)"),
                    "format": _("JSON-LD 1.1"),
                    "badge": "JSON-LD",
                    "previewTitle": _("Domain Context (JSON-LD 1.1)"),
                    "description": _(
                        "Semantic RDF / schema.org vocabulary mapping for Floppy "
                        "entities"
                    ),
                    "url": reverse("jsonld-context"),
                    "downloadName": "context.jsonld",
                },
                {
                    "label": _("Full Diagnostic API Schema"),
                    "format": _("Live OpenAPI (YAML)"),
                    "badge": _("Live"),
                    "previewTitle": _(
                        "Full Diagnostic API Schema (Live OpenAPI)"
                    ),
                    "description": _(
                        "Dynamically generated OpenAPI schema covering all active "
                        "routes on this instance"
                    ),
                    "url": reverse("schema"),
                    "downloadName": "openapi-live.yaml",
                },
                {
                    "label": _("Asynchronous Channels (AsyncAPI)"),
                    "format": _("AsyncAPI 3.0.0 (JSON)"),
                    "badge": "AsyncAPI",
                    "previewTitle": _(
                        "Asynchronous Channels (AsyncAPI 3.0.0)"
                    ),
                    "description": _(
                        "Inbound webhook routes, Celery queues, and worker "
                        "concurrency profiles"
                    ),
                    "url": reverse("asyncapi-contract"),
                    "downloadName": "asyncapi.json",
                },
            ],
        },
        "attributions": {
            "kind": "attributions",
            "labels": labels["attributions"],
            "icons": {"page": file_icon("page")},
            "items": [
                {
                    "provider": _("The Movie Database (TMDB)"),
                    "media": _(
                        "Movies, TV Shows, Seasons, Episodes & Cast/Crew Credits"
                    ),
                    "url": "https://www.themoviedb.org/",
                },
                {
                    "provider": "IGDB",
                    "media": _(
                        "Video Games, Platforms, Developers & Publishers"
                    ),
                    "url": "https://www.igdb.com/",
                },
                {
                    "provider": "MusicBrainz",
                    "media": _(
                        "Music Releases, Artists, Discographies & Tracklists"
                    ),
                    "url": "https://musicbrainz.org/",
                },
                {
                    "provider": _("Hardcover & Open Library"),
                    "media": _("Books, Authors, Editions & Page Counts"),
                    "url": "https://hardcover.app/",
                },
                {
                    "provider": "JustWatch",
                    "media": _(
                        "Streaming, Rent & Buy Availability Across Regions"
                    ),
                    "url": "https://www.justwatch.com/",
                },
                {
                    "provider": "OpenSubtitles",
                    "media": _("Multilingual Subtitles Synchronization"),
                    "url": "https://www.opensubtitles.com/",
                },
                {
                    "provider": "Pocket Casts",
                    "media": _(
                        "Podcast RSS Directories, Episode Feeds & Artwork"
                    ),
                    "url": "https://pocketcasts.com/",
                },
            ],
        },
        "licenses": {
            "kind": "licenses",
            "labels": labels["licenses"],
            "icons": {"page": file_icon("page")},
            "items": [
                {
                    "subject": _("Floppy Application"),
                    "terms": _(
                        "GNU Affero General Public License v3.0 (AGPL-3.0)"
                    ),
                    "url": (
                        "https://github.com/dannyvfilms/Floppy/blob/release/LICENSE"
                    ),
                },
                {
                    "subject": _("Upstream Heritage"),
                    "terms": _(
                        "Yamtrack (Original codebase fork; CSV exports supported)"
                    ),
                    "url": "https://github.com/FuzzyGrim/Yamtrack",
                },
            ],
        },
        "version": {
            "kind": "version",
            "labels": labels["version"],
            "version": settings.VERSION,
            "commit": settings.COMMIT_SHA_SHORT,
        },
    }
