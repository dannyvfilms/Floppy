"""OpenAPI schema class that publishes each operation's required token scope.

Lives apart from ``api.schema`` because DRF resolves ``DEFAULT_SCHEMA_CLASS``
while ``drf_spectacular.views`` is being imported, and ``api.schema`` imports
that module.
"""

from drf_spectacular.openapi import AutoSchema

from api.scopes import ANY_SCOPE, NEVER, resolve_required_scope


class ScopedAutoSchema(AutoSchema):
    """Annotate operations with the scope an integration token needs.

    Client authors otherwise have to guess which scopes to request, and a wrong
    guess only surfaces as a 403 at runtime.
    """

    def get_operation(self, *args, **kwargs):
        """Return the operation, annotated with its required scope."""
        operation = super().get_operation(*args, **kwargs)
        if not operation:
            return operation

        scope = resolve_required_scope(self.view, self.method)
        if scope == ANY_SCOPE:
            operation["x-required-scope"] = "any"
        elif scope == NEVER:
            operation["x-required-scope"] = "none (session or account token only)"
        elif scope:
            operation["x-required-scope"] = scope
        return operation
