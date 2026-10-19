"""Every published multi-container stack must put its services on one network.

Floppy reaches Redis and Postgres by service name (``redis://redis:6379``,
``DB_HOST=db``). Docker resolves those names only on a user-defined network.
Plain ``docker compose`` creates one implicitly, but Portainer, ZimaOS, CasaOS
and similar GUIs can drop the stack onto the default bridge network instead,
where no name resolves and every import fails to queue (#1166, #1229, #1263).
Declaring the network explicitly removes that dependence on the tool.

These tests read the stacks people actually copy: the checked-in compose files,
the guided installers' templates, and the compose blocks in the deployment
guide.
"""

import re
from pathlib import Path

import yaml
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.postgres.yml",
    ROOT / "scripts" / "install" / "templates" / "docker-compose.install.yml.tmpl",
)
DEPLOYMENT_GUIDE = ROOT / "docs" / "deployment.md"
WINDOWS_INSTALLER = ROOT / "scripts" / "install.ps1"
# The Windows installer writes its Compose file from a PowerShell here-string.
PS_COMPOSE = re.compile(r'WriteText \$script:ComposeFile @"\n(.*?)\n"@', re.DOTALL)
PS_VARIABLE = re.compile(r"\$\{?\w+\}?")
YAML_BLOCK = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)
# The installer template's @@NAME@@ placeholders are not valid YAML scalars.
TEMPLATE_PLACEHOLDER = re.compile(r"@@\w+@@")


def _load(text):
    return yaml.safe_load(TEMPLATE_PLACEHOLDER.sub("placeholder", text))


def _published_stacks():
    """Yield (label, parsed compose) for every stack with more than one service.

    Single-service guide snippets are fragments that show one setting, not a
    stack someone deploys on its own, and have no second container to reach.
    """
    for path in COMPOSE_FILES:
        yield path.name, _load(path.read_text(encoding="utf-8"))

    windows = PS_COMPOSE.search(WINDOWS_INSTALLER.read_text(encoding="utf-8"))
    yield "install.ps1", _load(PS_VARIABLE.sub("placeholder", windows.group(1)))

    text = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")
    for match in YAML_BLOCK.finditer(text):
        parsed = _load(match.group(1))
        if not isinstance(parsed, dict):
            continue
        if len(parsed.get("services") or {}) < 2:
            continue
        line = text[: match.start()].count("\n") + 1
        yield f"deployment.md:{line}", parsed


def _service_networks(service):
    # Compose accepts a list of names or a mapping of name to options.
    return set(service.get("networks") or [])


class PublishedComposeNetworkTests(SimpleTestCase):
    def test_every_stack_persists_app_data_and_backups(self):
        for label, stack in _published_stacks():
            mounts = stack["services"]["floppy"].get("volumes", [])
            targets = {mount.split(":")[1] for mount in mounts}
            with self.subTest(stack=label):
                self.assertIn("/floppy/db", targets)
                self.assertIn("/floppy/backups", targets)

    def test_example_stacks_do_not_ship_a_shared_signing_key(self):
        for label, stack in _published_stacks():
            environment = stack["services"]["floppy"].get("environment", {})
            if isinstance(environment, list):
                environment = dict(entry.partition("=")[::2] for entry in environment)
            with self.subTest(stack=label):
                value = environment.get("SECRET", "")
                self.assertTrue(
                    not value or value.startswith("${"),
                    f"{label} ships a fixed Django signing key",
                )

    def test_datastores_are_not_published_or_on_external_networks(self):
        for label, stack in _published_stacks():
            for name in ("redis", "db"):
                service = stack["services"].get(name)
                if service is None:
                    continue
                with self.subTest(stack=label, service=name):
                    self.assertFalse(service.get("ports"))
                    self.assertNotEqual(service.get("network_mode"), "host")
                    for network in _service_networks(service):
                        self.assertFalse((stack["networks"][network] or {}).get("external"))

    def test_the_guide_stacks_are_found(self):
        """Guard the guard: a regex change must not silently check nothing."""
        labels = [label for label, _stack in _published_stacks()]
        guide_stacks = [label for label in labels if label.startswith("deployment")]
        self.assertGreaterEqual(len(guide_stacks), 2, labels)
        self.assertIn("install.ps1", labels)

    def test_every_service_joins_a_declared_network(self):
        for label, stack in _published_stacks():
            with self.subTest(stack=label):
                declared = set(stack.get("networks") or {})
                self.assertTrue(
                    declared,
                    f"{label} declares no top-level network, so service names "
                    "only resolve if the deploying tool creates one",
                )
                shared = None
                for name, service in stack["services"].items():
                    joined = _service_networks(service)
                    self.assertTrue(
                        joined & declared,
                        f"{label}: service {name!r} joins none of {sorted(declared)}",
                    )
                    shared = joined if shared is None else shared & joined
                self.assertTrue(
                    shared,
                    f"{label}: services do not share one network",
                )

    def test_no_service_pins_a_network_mode(self):
        """network_mode: bridge puts a service on the network with no DNS."""
        for label, stack in _published_stacks():
            for name, service in stack["services"].items():
                with self.subTest(stack=label, service=name):
                    self.assertNotIn("network_mode", service)
