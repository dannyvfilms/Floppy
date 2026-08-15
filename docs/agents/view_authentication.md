# View Authentication and Public Route Exemption

This guide explains how Floppy controls access to HTTP views and routes.

## Architecture

Floppy enforces authentication for all views by default.

The application configures Django's core middleware in `src/config/settings.py`:

```python
MIDDLEWARE = [
    ...,
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    ...,
]
```

`LoginRequiredMiddleware` redirects unauthenticated (anonymous) requests to `/accounts/login/` unless a view explicitly declares an exemption.

```
       HTTP Request
            │
            ▼
┌───────────────────────────────────────┐
│       AuthenticationMiddleware        │
│       (Populates request.user)        │
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│        LoginRequiredMiddleware        │
│  Is view exempt via @login_not_required?
└───────┬───────────────────────┬───────┘
        │ Yes                   │ No
        ▼                       ▼
┌───────────────┐       ┌───────────────────────────────┐
│ Execute View  │       │ Is request.user authenticated? │
└───────────────┘       └───────┬───────────────┬───────┘
                                │ Yes           │ No
                                ▼               ▼
                        ┌───────────────┐ ┌────────────────────────┐
                        │ Execute View  │ │ 302 Redirect to Login  │
                        └───────────────┘ └────────────────────────┘
```

## How to Make a View Public

To make a view accessible without authentication, use the `@login_not_required` decorator from `django.contrib.auth.decorators`.

### 1. Function-Based Views

Apply `@login_not_required` directly to the view function:

```python
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@login_not_required
@require_GET
def public_endpoint(request):
    """Return data accessible without authentication."""
    return JsonResponse({"status": "ok"})
```

### 2. Class-Based Views in `urls.py`

Wrap `View.as_view()` with `login_not_required` in the URL pattern definition:

```python
from django.contrib.auth.decorators import login_not_required
from django.urls import path
from myapp.views import PublicDataView

urlpatterns = [
    path("public-data/", login_not_required(PublicDataView.as_view()), name="public_data"),
]
```

### 3. Class-Based Views via Method Decorator

Apply `@method_decorator(login_not_required, name="dispatch")` to the class:

```python
from django.contrib.auth.decorators import login_not_required
from django.utils.decorators import method_decorator
from django.views import View


@method_decorator(login_not_required, name="dispatch")
class PublicPageView(View):
    def get(self, request):
        ...
```

## Retired Setting: `LOGIN_REQUIRED_EXEMPT`

Previous iterations included a setting named `LOGIN_REQUIRED_EXEMPT` in `settings.py`.

- Django's built-in `LoginRequiredMiddleware` does **not** read any setting or list of regex paths.
- Route-level exemption lists in settings are unsupported and have been removed.
- Adding a route path to settings will not make it public. You must use `@login_not_required`.

## Established Public Routes

The following endpoints in Floppy are intentionally public:

| Route Path / Pattern | Purpose | Exemption Mechanism |
|---|---|---|
| `/health/` | Liveness probe for container checks | `login_not_required(MainView.as_view())` in `config/urls.py` |
| `/ping/` | Fast ping endpoint | `login_not_required(...)` in `config/urls.py` |
| `/serviceworker.js` | PWA offline service worker | `@login_not_required` on `service_worker` in `app/views.py` |
| `/list/<reference>/rss` | Public list RSS feeds | `@login_not_required` on `list_rss_feed` in `lists/feeds.py` |
| `/list/<reference>/json` | Public list JSON export | `@login_not_required` on `list_json` in `lists/feeds.py` |
| `/list/<reference>` | Public list detail page | `@login_not_required` on `list_detail` in `lists/views.py` |
| `/list/<reference>/export` | Public list CSV export | `@login_not_required` on `list_export_csv` in `lists/views.py` |
| `/api/schema/`, `/api/docs/` | OpenAPI schema and Swagger UI | `@login_not_required` on API contract views |
| `/accounts/login/`, `/signup/` | Authentication workflows | Handled by `django-allauth` account views |

## Testing Requirements

When you create a public view:

1. Add a test sending an unauthenticated request (`self.client.get(...)` without `force_login` or `login`).
2. Assert the response returns HTTP 200 (or the expected status code).
3. Assert the response does not return HTTP 302 redirecting to `/accounts/login/`.
4. Run `SECRET=test-only scripts/test.sh config.tests.test_login_required`.
