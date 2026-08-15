import ast
import inspect
import json
from unittest.mock import patch
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup
from django.conf import settings
from django.test import RequestFactory, SimpleTestCase
from django.test.utils import override_settings
from django.urls import get_script_prefix, reverse, set_script_prefix
from drf_spectacular.renderers import OpenApiYamlRenderer
from floppy_mcp import server as mcp_server
from floppy_mcp.http_manifest import (
    MCP_HTTP_MANIFEST,
    HTTPRoute,
    canonical_openapi_path,
)

from api.contract_views import api_docs
from api.helpers import MEDIA_TYPE_VALID_LIST
from api.schema_contract import (
    EXPECTED_SCHEMA_ERRORS,
    EXPECTED_SCHEMA_WARNINGS,
    SCHEMA_REGENERATION_COMMAND,
    VERIFIED_OPERATIONS,
    assert_schema_findings,
    generate_schema_contract,
    generate_static_schema_contract,
    normalize_schema_findings,
)
from app.domain_vocabulary import (
    DOMAIN_TERMS,
    FLOPPY_NAMESPACE,
    SCHEMA_ORG_NAMESPACE,
    class_name,
    property_name,
    render_glossary_rows,
    render_jsonld_context,
)

OPENAPI_CONTRACT_PATH = settings.BASE_DIR / "api" / "contracts" / "openapi.yaml"
JSONLD_CONTEXT_PATH = settings.BASE_DIR / "api" / "contracts" / "context.jsonld"


class OfflineAPIDocsTests(SimpleTestCase):
    def get_docs(self):
        response = self.client.get(reverse("swagger-ui"))
        return response, BeautifulSoup(response.content, "html.parser")

    def test_docs_are_public_and_use_the_offline_template(self):
        response, _ = self.get_docs()

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "api/docs.html")
        self.assertNotIn("app_base_url", response.context)

    def test_docs_support_head_without_rendering_a_response_body(self):
        get_response = self.client.get(reverse("swagger-ui"))
        response = self.client.head(reverse("swagger-ui"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        if response.has_header("Content-Length"):
            self.assertEqual(
                int(response.headers["Content-Length"]), len(get_response.content)
            )

    def test_docs_have_clear_landmarks_and_heading_order(self):
        _, soup = self.get_docs()

        self.assertIsNotNone(soup.find("header"))
        self.assertIsNotNone(soup.find("nav", attrs={"aria-label": "API tasks"}))
        main = soup.find("main", id="main-content")
        self.assertIsNotNone(main)
        self.assertIsNotNone(soup.find("footer"))
        self.assertEqual(len(soup.find_all("h1")), 1)
        self.assertEqual(
            [heading.get_text(" ", strip=True) for heading in main.find_all("h2")],
            ["Start with a task", "First request", "Domain model", "API schemas"],
        )
        skip_link = soup.find("a", href="#main-content")
        self.assertIsNotNone(skip_link)
        self.assertEqual(skip_link.get_text(" ", strip=True), "Skip to content")

    def test_task_navigation_has_four_ordered_single_task_links(self):
        _, soup = self.get_docs()
        task_links = soup.find("nav", attrs={"aria-label": "API tasks"}).find_all("a")

        self.assertEqual(
            [link.get("href") for link in task_links],
            [
                "#domain-model",
                "#first-request",
                reverse("schema"),
                reverse("openapi-contract"),
            ],
        )
        self.assertEqual(len(task_links), 4)

    def test_first_request_has_public_and_authenticated_commands(self):
        _, soup = self.get_docs()
        first_request = soup.select_one("#first-request")

        self.assertEqual(
            [heading.get_text(" ", strip=True) for heading in first_request.find_all("h3")],
            ["Check the connection", "Authenticated request"],
        )
        public_command = soup.select_one("#connection-command").get_text()
        authenticated_command = soup.select_one("#authenticated-command").get_text()
        self.assertEqual(
            public_command,
            f'curl --request GET "https://YOUR_FLOPPY_HOST{reverse("api_info")}/"',
        )
        self.assertNotIn("X-API-Key", public_command)
        self.assertIn("needs no API token", first_request.get_text(" ", strip=True))
        self.assertEqual(
            authenticated_command,
            'curl --request GET --header "X-API-Key: YOUR_API_TOKEN" '
            f'"https://YOUR_FLOPPY_HOST{reverse("api_user_preferences")}/"',
        )
        settings_link = soup.find("a", string="Settings -> Integrations")
        self.assertIsNotNone(settings_link)
        self.assertEqual(settings_link.get("href"), reverse("integrations"))
        self.assertEqual(
            settings_link.parent.get_text().strip(),
            "Copy your API Token in Settings -> Integrations.",
        )

    @override_settings(
        URLS=["https://floppy.example.test"],
        ALLOWED_HOSTS=["attacker.example.test"],
    )
    def test_commands_use_startup_script_prefix_once(self):
        original_prefix = get_script_prefix()
        try:
            set_script_prefix("/floppy/")
            request = RequestFactory().get(
                "/floppy/api/docs/", HTTP_HOST="attacker.example.test"
            )
            response = api_docs(request)
        finally:
            set_script_prefix(original_prefix)

        soup = BeautifulSoup(response.content, "html.parser")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            soup.select_one("#connection-command").get_text(),
            'curl --request GET "https://floppy.example.test/floppy/api/v1/info/"',
        )
        self.assertEqual(
            soup.select_one("#authenticated-command").get_text(),
            'curl --request GET --header "X-API-Key: YOUR_API_TOKEN" '
            '"https://floppy.example.test/floppy/api/v1/user/preferences/"',
        )
        self.assertNotIn("/floppy/floppy/", response.content.decode())
        self.assertNotIn("attacker.example.test", response.content.decode())

    @override_settings(URLS=[], BASE_URL=None, ALLOWED_HOSTS=["attacker.example.test"])
    def test_commands_never_fall_back_to_request_host(self):
        response = self.client.get(
            reverse("swagger-ui"), HTTP_HOST="attacker.example.test"
        )
        soup = BeautifulSoup(response.content, "html.parser")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            soup.select_one("#connection-command").get_text(),
            f'curl --request GET "https://YOUR_FLOPPY_HOST{reverse("api_info")}/"',
        )
        self.assertEqual(
            soup.select_one("#authenticated-command").get_text(),
            'curl --request GET --header "X-API-Key: YOUR_API_TOKEN" '
            f'"https://YOUR_FLOPPY_HOST{reverse("api_user_preferences")}/"',
        )
        self.assertNotIn("attacker.example.test", response.content.decode())

    @override_settings(
        URLS=[],
        BASE_URL="https://floppy.example.test",
        ALLOWED_HOSTS=["attacker.example.test"],
    )
    def test_commands_use_absolute_base_url_not_request_host(self):
        response = self.client.get(
            reverse("swagger-ui"), HTTP_HOST="attacker.example.test"
        )

        content = response.content.decode()
        self.assertIn(
            f'"https://floppy.example.test{reverse("api_info")}/"', content
        )
        self.assertIn(
            f'"https://floppy.example.test{reverse("api_user_preferences")}/"',
            content,
        )
        self.assertNotIn("attacker.example.test", content)

    def test_docs_render_the_approved_domain_glossary(self):
        response, soup = self.get_docs()
        expected = render_glossary_rows()

        self.assertEqual(response.context["glossary_terms"], expected)
        self.assertEqual(
            tuple(
                {
                    "key": row["id"].removeprefix("term-"),
                    "term": row.find("dt").get_text(" ", strip=True),
                    "definition": row.find("dd").get_text(" ", strip=True),
                }
                for row in soup.select("#domain-model .glossary-row")
            ),
            expected,
        )

    def test_docs_distinguish_the_dynamic_and_committed_schemas(self):
        _, soup = self.get_docs()
        dynamic = soup.select_one("#dynamic-schema")
        committed = soup.select_one("#committed-schema")

        self.assertIn("full schema", dynamic.get_text(" ", strip=True).lower())
        self.assertIn("generated dynamically", dynamic.get_text(" ", strip=True).lower())
        self.assertIn("diagnostics", dynamic.get_text(" ", strip=True).lower())
        self.assertEqual(dynamic.find("a").get("href"), reverse("schema"))
        self.assertIn("reviewed", committed.get_text(" ", strip=True).lower())
        self.assertIn("committed", committed.get_text(" ", strip=True).lower())
        self.assertIn("versioned subset", committed.get_text(" ", strip=True).lower())
        self.assertIn("supported integrations", committed.get_text(" ", strip=True).lower())
        self.assertIn("mcp grounding", committed.get_text(" ", strip=True).lower())
        self.assertIn("41 operations", committed.get_text(" ", strip=True).lower())
        self.assertEqual(
            committed.find("a").get("href"), reverse("openapi-contract")
        )

    def test_docs_have_no_swagger_or_executable_request_ui(self):
        response, soup = self.get_docs()
        html = response.content.decode().lower()

        self.assertNotIn("swagger", html)
        self.assertEqual(soup.find_all("script"), [])
        self.assertEqual(soup.select("[src], link[rel~='stylesheet']"), [])
        self.assertEqual(
            soup.find_all(["form", "button", "input", "select", "textarea"]), []
        )

    def test_inline_css_supports_focus_reflow_and_dark_colors_without_motion(self):
        _, soup = self.get_docs()
        css = soup.find("style").get_text().lower()

        self.assertIn(":focus-visible", css)
        self.assertIn("max-width: 70ch", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("color-scheme: light dark", css)
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIsNotNone(soup.find("meta", attrs={"name": "viewport"}))
        for forbidden in (
            "animation",
            "transition",
            "scroll-behavior",
            "min-width",
        ):
            self.assertNotIn(forbidden, css)

    @patch("drf_spectacular.generators.SchemaGenerator.get_schema")
    def test_docs_do_not_generate_a_schema(self, get_schema):
        response, _ = self.get_docs()

        self.assertEqual(response.status_code, 200)
        get_schema.assert_not_called()


class OpenAPIArtifactTests(SimpleTestCase):
    @staticmethod
    def _operations(schema):
        return {
            (path, method.upper())
            for path, path_item in schema["paths"].items()
            for method in path_item
            if method in {"get", "post", "put", "patch", "delete"}
        }

    def test_settings_publish_stable_project_metadata(self):
        self.assertEqual(
            settings.SPECTACULAR_SETTINGS,
            {
                "TITLE": "Floppy",
                "DESCRIPTION": "A self-hosted media tracker.",
                "VERSION": "1.0.0",
                "CONTACT": {
                    "url": "https://github.com/dannyvfilms/Floppy/issues",
                },
                "LICENSE": {
                    "name": "AGPL-3.0",
                    "url": "https://www.gnu.org/licenses/agpl-3.0.html",
                },
                "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
            },
        )

    def test_committed_contract_is_exact_verified_generation(self):
        committed = OPENAPI_CONTRACT_PATH.read_bytes()
        parsed = yaml.safe_load(committed)
        generated = generate_static_schema_contract()

        self.assertEqual(parsed["openapi"], "3.0.3")
        self.assertEqual(generated.errors, frozenset())
        self.assertEqual(generated.warnings, frozenset())
        self.assertEqual(self._operations(parsed), VERIFIED_OPERATIONS)
        self.assertEqual(committed, OpenApiYamlRenderer().render(generated.schema))

    @override_settings(VERSION="application-version-must-not-leak")
    def test_contract_is_deterministic_and_independent_of_application_version(self):
        first = OpenApiYamlRenderer().render(generate_static_schema_contract().schema)
        second = OpenApiYamlRenderer().render(generate_static_schema_contract().schema)

        self.assertEqual(first, second)
        self.assertEqual(first, OPENAPI_CONTRACT_PATH.read_bytes())
        self.assertEqual(yaml.safe_load(first)["info"]["version"], "1.0.0")

    def test_contract_is_clearly_scoped_and_subpath_safe(self):
        schema = generate_static_schema_contract().schema

        self.assertIn(
            "verified consumer subset", schema["info"]["description"].lower()
        )
        self.assertEqual(
            schema["x-floppy-scope"], "verified-mcp-and-grounding-subset"
        )
        self.assertEqual(schema["servers"], [{"url": "../"}])

        with override_settings(BASE_URL="/floppy"):
            self.assertEqual(
                urljoin(
                    "https://example.test/floppy/api/openapi.yaml",
                    schema["servers"][0]["url"],
                ),
                "https://example.test/floppy/",
            )

    def test_contract_has_truthful_wire_components_and_auth_schemes(self):
        components = generate_static_schema_contract().schema["components"]
        schemas = components["schemas"]

        self.assertEqual(
            set(schemas["SearchResult"]["required"]),
            {"media_id", "source", "media_type", "title", "image"},
        )
        self.assertEqual(
            schemas["SearchResult"]["properties"]["media_id"]["oneOf"],
            [{"type": "string"}, {"type": "integer"}],
        )
        self.assertEqual(
            set(schemas["SearchEnvelope"]["required"]), {"pagination", "results"}
        )
        self.assertEqual(
            set(schemas["TrackMediaRequest"]["properties"]),
            {
                "source",
                "media_id",
                "title",
                "image",
                "image_url",
                "season_number",
                "episode_number",
                "parent_tv",
                "parent_season",
                "library_media_type",
                "score",
                "status",
                "progress",
                "start_date",
                "end_date",
                "notes",
            },
        )
        self.assertEqual(
            set(schemas["MediaUpdateRequest"]["properties"]),
            {
                "score",
                "status",
                "progress",
                "start_date",
                "end_date",
                "notes",
            },
        )
        self.assertEqual(
            set(schemas["TrackedMediaResponse"]["properties"]),
            {
                "id",
                "consumption_id",
                "item",
                "item_id",
                "parent_id",
                "tracked",
                "created_at",
                "score",
                "status",
                "progress",
                "progress_scope",
                "progress_unit",
                "progressed_at",
                "start_date",
                "end_date",
                "notes",
                "lists",
            },
        )
        self.assertEqual(
            set(schemas["ConsumptionResponse"]["properties"]),
            {
                "consumption_id",
                "created",
                "score",
                "progress",
                "progressed_at",
                "status",
                "start_date",
                "end_date",
                "notes",
            },
        )
        complete_keys = {
            "id",
            "media_id",
            "source",
            "source_url",
            "media_type",
            "title",
            "max_progress",
            "image",
            "synopsis",
            "genres",
            "score",
            "score_count",
            "details",
            "related",
            "item_id",
            "parent_id",
            "tracked",
            "consumptions_number",
            "consumptions",
            "lists",
        }
        self.assertEqual(
            set(schemas["CompleteMediaResponse"]["properties"]), complete_keys
        )
        self.assertEqual(
            set(schemas["CompleteEpisodeResponse"]["properties"]), complete_keys
        )
        self.assertNotIn(
            "season_number", schemas["CompleteEpisodeResponse"]["properties"]
        )
        self.assertNotIn(
            "episode_number", schemas["CompleteEpisodeResponse"]["properties"]
        )
        self.assertTrue(
            {"season_number", "episode_number"}
            <= set(schemas["EpisodeDetails"]["properties"])
        )
        self.assertEqual(
            set(schemas["InfoResponse"]["properties"]),
            {
                "version",
                "debug",
                "frontend_url",
                "language",
                "timezone",
                "admin_enabled",
                "track_time",
            },
        )
        self.assertEqual(
            components["securitySchemes"],
            {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                },
                "bearerAuth": {"type": "http", "scheme": "bearer"},
                "listenBrainzToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "Authorization",
                    "description": "ListenBrainz token in the form `Token <token>`.",
                },
            },
        )

    def test_critical_operations_use_exact_requests_responses_and_statuses(self):
        paths = generate_static_schema_contract().schema["paths"]
        expected = {
            ("/api/v1/search/{media_type}/", "get"): (
                "searchMedia",
                "SearchEnvelope",
                {"200", "400", "403", "500"},
                None,
            ),
            ("/api/v1/media/{media_type}/", "post"): (
                "trackMedia",
                "TrackedMediaResponse",
                {"201", "400", "403", "404", "409", "500"},
                "TrackMediaRequest",
            ),
            ("/api/v1/media/{media_type}/{source}/{media_id}/", "get"): (
                "retrieveMediaItem",
                "CompleteMediaResponse",
                {"200", "400", "403", "404", "500"},
                None,
            ),
            ("/api/v1/media/{media_type}/{source}/{media_id}/", "patch"): (
                "updateMediaItem",
                "CompleteMediaResponse",
                {"200", "400", "403", "404", "500"},
                "MediaUpdateRequest",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/history/"
                "{consumption_id}/",
                "patch",
            ): (
                "updateMediaConsumption",
                "ConsumptionResponse",
                {"200", "400", "403", "404", "500"},
                "MediaUpdateRequest",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/",
                "get",
            ): (
                "retrieveMediaSeason",
                "CompleteMediaResponse",
                {"200", "400", "403", "404", "500"},
                None,
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/",
                "get",
            ): (
                "retrieveMediaEpisode",
                "CompleteEpisodeResponse",
                {"200", "400", "403", "404", "500"},
                None,
            ),
        }

        for (path, method), (
            operation_id,
            component,
            statuses,
            request_component,
        ) in expected.items():
            with self.subTest(path=path, method=method):
                operation = paths[path][method]
                self.assertEqual(operation["operationId"], operation_id)
                self.assertEqual(set(operation["responses"]), statuses)
                success = "201" if method == "post" else "200"
                response = operation["responses"][success]
                schema = response["content"]["application/json"]["schema"]
                self.assertEqual(schema["$ref"], f"#/components/schemas/{component}")
                if request_component:
                    request_schema = operation["requestBody"]["content"][
                        "application/json"
                    ]["schema"]
                    self.assertEqual(
                        request_schema["$ref"],
                        f"#/components/schemas/{request_component}",
                    )
                self.assertEqual(
                    operation["security"],
                    [{"bearerAuth": []}, {"ApiKeyAuth": []}],
                )

    def test_search_media_type_enum_matches_supported_provider_types(self):
        operation = generate_static_schema_contract().schema["paths"][
            "/api/v1/search/{media_type}/"
        ]["get"]
        media_type = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "path" and parameter["name"] == "media_type"
        )

        self.assertEqual(media_type["schema"]["enum"], sorted(MEDIA_TYPE_VALID_LIST))
        self.assertNotIn("season", media_type["schema"]["enum"])
        self.assertNotIn("episode", media_type["schema"]["enum"])

    def test_list_latest_update_allows_empty_list_null(self):
        paths = generate_static_schema_contract().schema["paths"]
        post_schema = paths["/api/v1/lists/"]["post"]["responses"]["201"][
            "content"
        ]["application/json"]["schema"]
        get_schema = paths["/api/v1/lists/"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["properties"]["results"]["items"]

        self.assertTrue(post_schema["properties"]["latest_update"]["nullable"])
        self.assertTrue(get_schema["properties"]["latest_update"]["nullable"])

    def test_listenbrainz_and_info_operations_are_exact(self):
        paths = generate_static_schema_contract().schema["paths"]
        for path, method, operation_id, statuses in (
            (
                "/apis/listenbrainz/1/submit-listens/",
                "post",
                "submitListenBrainzListens",
                {"200", "400", "401", "403"},
            ),
            (
                "/apis/listenbrainz/1/validate-token/",
                "get",
                "validateListenBrainzToken",
                {"200", "401"},
            ),
        ):
            operation = paths[path][method]
            self.assertEqual(operation["operationId"], operation_id)
            self.assertEqual(operation["security"], [{"listenBrainzToken": []}])
            self.assertEqual(set(operation["responses"]), statuses)

        info = paths["/api/v1/info/"]["get"]
        self.assertEqual(info.get("security"), None)
        self.assertEqual(
            info["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/InfoResponse"},
        )

    def test_all_successful_scoped_operations_have_truthful_body_presence(self):
        paths = generate_static_schema_contract().schema["paths"]
        operation_ids = [
            operation["operationId"]
            for path_item in paths.values()
            for method, operation in path_item.items()
            if method in {"get", "post", "put", "patch", "delete"}
        ]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for status, response in operation["responses"].items():
                    if method != "delete" and status.startswith("2"):
                        with self.subTest(path=path, method=method, status=status):
                            self.assertIn("schema", response["content"]["application/json"])


class JSONLDContextTests(SimpleTestCase):
    """Gate the committed JSON-LD context and its public route."""

    def _context(self):
        return json.loads(JSONLD_CONTEXT_PATH.read_text(encoding="utf-8"))["@context"]

    def test_committed_context_matches_the_vocabulary_renderer(self):
        self.assertEqual(
            JSONLD_CONTEXT_PATH.read_bytes(),
            render_jsonld_context().encode("utf-8"),
        )

    def test_context_is_jsonld_11_with_the_stable_project_namespace(self):
        context = self._context()

        self.assertEqual(context["@version"], 1.1)
        self.assertEqual(context["floppy"], FLOPPY_NAMESPACE)
        self.assertEqual(context["schema"], SCHEMA_ORG_NAMESPACE)
        self.assertEqual(FLOPPY_NAMESPACE, "https://github.com/dannyvfilms/Floppy/ns#")

    def test_context_reads_linked_data_fields_only(self):
        """Definitions, aliases and bounded contexts stay out of the artifact."""
        raw = JSONLD_CONTEXT_PATH.read_text(encoding="utf-8")

        for term in DOMAIN_TERMS:
            with self.subTest(term=term.key):
                self.assertNotIn(term.definition, raw)
                self.assertNotIn(f'"{term.bounded_context}"', raw)
                for alias in term.aliases:
                    self.assertNotIn(f'"{alias}"', raw)

    def test_every_term_has_a_context_entry_and_schema_org_is_mapped(self):
        context = self._context()

        for term in DOMAIN_TERMS:
            with self.subTest(term=term.key):
                self.assertIn(class_name(term.key), context)
        mapped = {
            term.schema_org.replace(SCHEMA_ORG_NAMESPACE, "schema:")
            for term in DOMAIN_TERMS
            if term.schema_org
        }
        self.assertTrue(mapped)
        for mapping in mapped:
            self.assertIn(mapping, context.values())

    def test_every_relationship_has_an_id_typed_property_term(self):
        context = self._context()
        relationships = [
            relationship
            for term in DOMAIN_TERMS
            for relationship, _ in term.relationships
        ]
        self.assertTrue(relationships)

        for relationship in relationships:
            name = property_name(relationship)
            with self.subTest(relationship=relationship):
                self.assertEqual(
                    context[name],
                    {"@id": f"floppy:{name}", "@type": "@id"},
                )

    def test_pyld_expands_every_class_and_relationship(self):
        """Cover the whole vocabulary, not a hand-picked subset."""
        from pyld import jsonld

        context = self._context()
        document = {"@context": context, "@type": class_name(DOMAIN_TERMS[0].key)}
        for term in DOMAIN_TERMS:
            for relationship, target in term.relationships:
                document[property_name(relationship)] = {
                    "@type": class_name(target),
                }

        expanded = jsonld.expand(document)[0]

        for term in DOMAIN_TERMS:
            for relationship, target in term.relationships:
                name = property_name(relationship)
                expected = (
                    DOMAIN_TERMS[
                        [t.key for t in DOMAIN_TERMS].index(target)
                    ].schema_org
                    or f"{FLOPPY_NAMESPACE}{target}"
                )
                with self.subTest(relationship=relationship):
                    self.assertEqual(
                        expanded[f"{FLOPPY_NAMESPACE}{name}"][0]["@type"],
                        [expected],
                    )

    def test_pyld_expands_the_context_to_absolute_iris(self):
        from pyld import jsonld

        expanded = jsonld.expand(
            {
                "@context": self._context(),
                "@type": "Item",
                "hasUserTrackingRecord": {"@type": "Consumption"},
                "isClassifiedBy": {"@type": "MediaType"},
            },
        )

        self.assertEqual(expanded[0]["@type"], ["https://schema.org/CreativeWork"])
        self.assertEqual(
            expanded[0][f"{FLOPPY_NAMESPACE}hasUserTrackingRecord"][0]["@type"],
            [f"{FLOPPY_NAMESPACE}consumption"],
        )
        self.assertEqual(
            expanded[0][f"{FLOPPY_NAMESPACE}isClassifiedBy"][0]["@type"],
            [f"{FLOPPY_NAMESPACE}media_type"],
        )

    def test_context_route_is_public_and_serves_the_committed_bytes(self):
        response = self.client.get(reverse("jsonld-context"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/ld+json")
        self.assertEqual(
            b"".join(response.streaming_content),
            JSONLD_CONTEXT_PATH.read_bytes(),
        )
        self.assertEqual(
            set(response["Cache-Control"].split(", ")),
            {"public", "max-age=3600"},
        )

    def test_context_route_supports_etag_revalidation_and_head(self):
        first = self.client.get(reverse("jsonld-context"))

        matched = self.client.get(
            reverse("jsonld-context"), HTTP_IF_NONE_MATCH=first["ETag"]
        )
        self.assertEqual(matched.status_code, 304)

        missed = self.client.get(
            reverse("jsonld-context"), HTTP_IF_NONE_MATCH='"stale"'
        )
        self.assertEqual(missed.status_code, 200)

        self.assertEqual(self.client.head(reverse("jsonld-context")).status_code, 200)

    def test_context_route_never_serves_the_contract_for_unsafe_methods(self):
        """Assert the invariant that holds in the deployed stack too.

        The test client sees 405 from ``require_safe``, but behind the real
        middleware stack an unsafe method is redirected to login (302) before
        the view runs - the same as ``/api/openapi.yaml`` and ``/api/docs/``.
        What matters either way is that POST never returns the artifact.
        """
        response = self.client.post(reverse("jsonld-context"))

        self.assertIn(response.status_code, {302, 405})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(hasattr(response, "streaming_content"))


class SchemaFindingContractTests(SimpleTestCase):
    def test_normalizes_unique_findings_without_volatile_rendering(self):
        findings = {
            "/home/example/checkout/src/api/views.py:123: Error [CalendarView]: "
            "unable to guess serializer. Volatile advice.": 7,
            "/another/checkout/src/api/listenbrainz_views.py: Warning "
            "[SubmitListensView]: could not resolve authenticator <class 'Changed'>.": 2,
            "/checkout/src/api/future.py: Error [FutureView]: new volatile prose": 1,
            'Warning: operationId "api_v1_media_retrieve" has collisions '
            "[('/api/v1/media/', 'get')]. volatile prose": 3,
        }

        self.assertEqual(
            normalize_schema_findings(findings),
            frozenset(
                {
                    ("api.views.CalendarView", "serializer-unresolved"),
                    (
                        "api.listenbrainz_views.SubmitListensView"
                        "[authenticator=Changed]",
                        "authentication-unresolved",
                    ),
                    ("api.future.FutureView", "unclassified"),
                    (
                        "operation-id.api_v1_media_retrieve"
                        "(('/api/v1/media/', 'get'),)",
                        "operation-id-collision",
                    ),
                }
            ),
        )

    def test_unresolved_authenticator_class_is_part_of_finding_identity(self):
        prefix = (
            "/checkout/src/api/views.py: Warning [AuthView]: "
            "could not resolve authenticator <class '"
        )

        listenbrainz = normalize_schema_findings(
            [f"{prefix}api.authentication.ListenBrainzTokenAuthentication'>."]
        )
        api_key = normalize_schema_findings(
            [f"{prefix}api.authentication.APIKeyAuthentication'>."]
        )

        self.assertNotEqual(listenbrainz, api_key)
        self.assertIn(
            (
                "api.views.AuthView"
                "[authenticator=api.authentication.ListenBrainzTokenAuthentication]",
                "authentication-unresolved",
            ),
            listenbrainz,
        )

    def test_operation_id_collision_members_are_part_of_finding_identity(self):
        prefix = 'Warning: operationId "api_v1_media_retrieve" has collisions '

        two_routes = normalize_schema_findings(
            [f"{prefix}[('/api/v1/media/', 'get'), ('/api/v1/media/{{id}}/', 'get')]."]
        )
        same_routes_reordered = normalize_schema_findings(
            [f"{prefix}[('/api/v1/media/{{id}}/', 'GET'), ('/api/v1/media/', 'get')]."]
        )
        three_routes = normalize_schema_findings(
            [
                f"{prefix}[('/api/v1/media/{{id}}/', 'get'), "
                "('/api/v1/media/{id}/{part}/', 'get'), "
                "('/api/v1/media/', 'get')]."
            ]
        )

        self.assertEqual(two_routes, same_routes_reordered)
        self.assertNotEqual(two_routes, three_routes)

    def test_baseline_failure_names_changed_pair_and_regeneration_command(self):
        removed = min(EXPECTED_SCHEMA_ERRORS)
        added = (f"{removed[0]}Changed", removed[1])
        mutated = (EXPECTED_SCHEMA_ERRORS - {removed}) | {added}

        with self.assertRaises(AssertionError) as caught:
            assert_schema_findings(mutated, EXPECTED_SCHEMA_WARNINGS)

        message = str(caught.exception)
        self.assertIn(f"+ {added!r}", message)
        self.assertIn(f"- {removed!r}", message)
        self.assertIn(SCHEMA_REGENERATION_COMMAND, message)

    def test_reviewed_baseline_has_expected_unique_counts(self):
        self.assertEqual(len(EXPECTED_SCHEMA_ERRORS), 83)
        self.assertEqual(len(EXPECTED_SCHEMA_WARNINGS), 18)

    def test_generated_schema_findings_match_reviewed_baseline(self):
        contract = generate_schema_contract()

        assert_schema_findings(contract.errors, contract.warnings)

    def test_static_schema_has_no_findings_and_full_schema_is_a_superset(self):
        static = generate_static_schema_contract()
        dynamic = generate_schema_contract()

        self.assertEqual(static.errors, frozenset())
        self.assertEqual(static.warnings, frozenset())
        assert_schema_findings(dynamic.errors, dynamic.warnings)
        self.assertTrue(
            OpenAPIArtifactTests._operations(static.schema)
            <= OpenAPIArtifactTests._operations(dynamic.schema)
        )


class MCPHTTPManifestTests(SimpleTestCase):
    def test_relative_paths_have_one_canonical_openapi_form(self):
        self.assertEqual(canonical_openapi_path("media/{media_type}"), "/api/v1/media/{media_type}/")
        self.assertEqual(canonical_openapi_path("/media/"), "/api/v1/media/")

    @staticmethod
    def _routes_from_source(source):
        routes = []

        def is_mcp_tool(node):
            return any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "mcp"
                and decorator.func.attr == "tool"
                for decorator in node.decorator_list
            )

        def path_template(node, line):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.JoinedStr):
                parts = []
                for value in node.values:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        parts.append(value.value)
                    elif (
                        isinstance(value, ast.FormattedValue)
                        and isinstance(value.value, ast.Name)
                        and value.conversion == -1
                        and value.format_spec is None
                    ):
                        parts.append(f"{{{value.value.id}}}")
                    else:
                        raise AssertionError(
                            f"Unsupported MCP path expression at line {line}"
                        )
                return "".join(parts)
            raise AssertionError(f"Unsupported MCP path expression at line {line}")

        for node in ast.parse(source).body:
            if not isinstance(node, ast.AsyncFunctionDef) or not is_mcp_tool(node):
                continue
            for call in ast.walk(node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "_call"
                ):
                    continue
                if len(call.args) < 2:
                    raise AssertionError(f"Invalid _call at line {call.lineno}")
                method = call.args[0]
                if not (
                    isinstance(method, ast.Constant)
                    and isinstance(method.value, str)
                    and method.value == method.value.lower()
                ):
                    raise AssertionError(
                        f"MCP method must be a lowercase string literal at line {call.lineno}"
                    )
                routes.append(
                    HTTPRoute(
                        node.name,
                        method.value,
                        canonical_openapi_path(
                            path_template(call.args[1], call.lineno)
                        ),
                    )
                )
        return routes

    def test_source_extractor_rejects_computed_paths(self):
        source = """
@mcp.tool()
async def computed_path():
    path = "home"
    return await _call("get", path)
"""
        with self.assertRaisesRegex(
            AssertionError, "Unsupported MCP path expression at line 5"
        ):
            self._routes_from_source(source)

    def test_source_extractor_requires_literal_lowercase_methods(self):
        for method in ("method", '"GET"'):
            with self.subTest(method=method), self.assertRaisesRegex(
                AssertionError,
                "MCP method must be a lowercase string literal at line 4",
            ):
                self._routes_from_source(
                    f"""
@mcp.tool()
async def invalid_method():
    return await _call({method}, "home")
"""
                )

    def test_source_extractor_preserves_exact_templates(self):
        source = """\
@mcp.tool()
async def exact_template():
    await _call("get", f"media/{media_type}/{source}/{media_id}")
    await _call("post", "unexercised")
"""
        expected = {
            HTTPRoute(
                "exact_template",
                "get",
                "/api/v1/media/{media_type}/{source}/{media_id}/",
            ),
            HTTPRoute("exact_template", "post", "/api/v1/unexercised/"),
        }

        self.assertEqual(set(self._routes_from_source(source)), expected)
        self.assertNotEqual(
            set(
                self._routes_from_source(
                    source.replace("{media_type}/{source}", "{source}/{media_type}")
                )
            ),
            expected,
        )
        self.assertIn(
            HTTPRoute("exact_template", "post", "/api/v1/unexercised/"),
            self._routes_from_source(source),
        )

    def test_manifest_covers_all_current_http_branches(self):
        routes = self._routes_from_source(inspect.getsource(mcp_server))

        self.assertEqual(len(MCP_HTTP_MANIFEST), 40)
        self.assertEqual(len(MCP_HTTP_MANIFEST), len(set(MCP_HTTP_MANIFEST)))
        self.assertEqual(set(routes), set(MCP_HTTP_MANIFEST))
        self.assertTrue(
            {"search_media", "get_media", "track_media"}
            <= {route.tool for route in routes}
        )

    def test_every_manifest_route_exists_in_committed_openapi(self):
        paths = yaml.safe_load(OPENAPI_CONTRACT_PATH.read_bytes())["paths"]

        missing = [
            entry
            for entry in MCP_HTTP_MANIFEST
            if entry.path not in paths or entry.method not in paths[entry.path]
        ]
        self.assertEqual(missing, [])
