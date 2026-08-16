from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from app import domain_vocabulary


class DomainVocabularyTests(SimpleTestCase):
    def test_registry_is_frozen_and_contains_the_required_terms(self):
        self.assertIsInstance(domain_vocabulary.DOMAIN_TERMS, tuple)
        self.assertEqual(
            tuple(term.term for term in domain_vocabulary.DOMAIN_TERMS),
            ("Item", "Consumption", "Media type", "Celery queue"),
        )

        with self.assertRaises(FrozenInstanceError):
            domain_vocabulary.DOMAIN_TERMS[0].term = "Changed"

    def test_definitions_record_the_grounding_facts(self):
        terms = {term.key: term for term in domain_vocabulary.DOMAIN_TERMS}

        self.assertIn("shared work", terms["item"].definition)
        self.assertIn(
            "one user's tracking record for an Item",
            terms["consumption"].definition,
        )
        self.assertIn("nested under `tv`", terms["media_type"].definition)
        self.assertIn(
            "not top-level media types",
            terms["media_type"].definition,
        )
        for queue in ("`celery`", "`interactive`", "`discover`"):
            self.assertIn(queue, terms["celery_queue"].definition)
        self.assertIn(
            "The Reload calendar task has no queue override, so it uses `celery` "
            "with background priority `9`.",
            terms["celery_queue"].definition,
        )

    def test_validator_rejects_duplicate_keys_terms_and_aliases(self):
        item = domain_vocabulary.DOMAIN_TERMS[0]
        consumption = domain_vocabulary.DOMAIN_TERMS[1]
        cases = (
            replace(consumption, key=item.key),
            replace(consumption, term=item.term.lower()),
            replace(consumption, aliases=(item.aliases[0].upper(),)),
        )

        for invalid_term in cases:
            with self.subTest(invalid_term=invalid_term):
                with self.assertRaises(ValueError):
                    domain_vocabulary.validate_terms((item, invalid_term))

    def test_validator_rejects_alias_term_collisions(self):
        item = domain_vocabulary.DOMAIN_TERMS[0]
        consumption = replace(
            domain_vocabulary.DOMAIN_TERMS[1],
            aliases=(item.term.lower(),),
        )

        with self.assertRaises(ValueError):
            domain_vocabulary.validate_terms((item, consumption))

    def test_validator_requires_relationship_targets_to_resolve(self):
        item = replace(
            domain_vocabulary.DOMAIN_TERMS[0],
            relationships=(("tracks", "missing"),),
        )

        with self.assertRaises(ValueError):
            domain_vocabulary.validate_terms((item,))

    def test_glossary_renderer_returns_template_rows(self):
        self.assertEqual(
            domain_vocabulary.render_glossary_rows(),
            tuple(
                {
                    "key": term.key,
                    "term": term.term,
                    "definition": term.definition,
                }
                for term in domain_vocabulary.DOMAIN_TERMS
            ),
        )

    def test_generated_guide_matches_the_renderer(self):
        rendered = domain_vocabulary.render_agent_guide().encode("utf-8")

        self.assertTrue(rendered.startswith(b"<!-- GENERATED FILE. DO NOT EDIT."))
        self.assertEqual(
            domain_vocabulary.GUIDE_PATH.read_bytes(),
            rendered,
        )

    def test_check_rejects_crlf_guide_bytes(self):
        rendered = domain_vocabulary.render_agent_guide().encode("utf-8")
        crlf_bytes = rendered.replace(b"\n", b"\r\n")
        self.assertNotEqual(crlf_bytes, rendered)

        with TemporaryDirectory() as directory:
            guide_path = Path(directory) / "domain_model.md"
            guide_path.write_bytes(crlf_bytes)
            context_path = Path(directory) / "context.jsonld"
            context_path.write_bytes(
                domain_vocabulary.render_jsonld_context().encode("utf-8")
            )
            with (
                patch.object(domain_vocabulary, "GUIDE_PATH", guide_path),
                patch.object(domain_vocabulary, "CONTEXT_PATH", context_path),
            ):
                self.assertEqual(domain_vocabulary.main(["--check"]), 1)

    def test_module_entry_point_writes_and_checks_both_artifacts(self):
        """Patch both paths so the run cannot touch the committed artifacts."""
        with TemporaryDirectory() as directory:
            guide_path = Path(directory) / "domain_model.md"
            context_path = Path(directory) / "context.jsonld"
            with (
                patch.object(domain_vocabulary, "GUIDE_PATH", guide_path),
                patch.object(domain_vocabulary, "CONTEXT_PATH", context_path),
            ):
                self.assertEqual(domain_vocabulary.main(["--check"]), 1)
                self.assertEqual(domain_vocabulary.main([]), 0)
                self.assertEqual(
                    guide_path.read_bytes(),
                    domain_vocabulary.render_agent_guide().encode("utf-8"),
                )
                self.assertEqual(
                    context_path.read_bytes(),
                    domain_vocabulary.render_jsonld_context().encode("utf-8"),
                )
                self.assertEqual(domain_vocabulary.main(["--check"]), 0)

                guide_path.write_bytes(b"drift\n")
                self.assertEqual(domain_vocabulary.main(["--check"]), 1)

    def test_check_detects_context_drift_on_its_own(self):
        """Guide in sync, context drifted: --check must still fail."""
        with TemporaryDirectory() as directory:
            guide_path = Path(directory) / "domain_model.md"
            context_path = Path(directory) / "context.jsonld"
            guide_path.write_bytes(
                domain_vocabulary.render_agent_guide().encode("utf-8")
            )
            with (
                patch.object(domain_vocabulary, "GUIDE_PATH", guide_path),
                patch.object(domain_vocabulary, "CONTEXT_PATH", context_path),
            ):
                # Missing context file.
                self.assertEqual(domain_vocabulary.main(["--check"]), 1)

                context_path.write_bytes(
                    domain_vocabulary.render_jsonld_context().encode("utf-8")
                )
                self.assertEqual(domain_vocabulary.main(["--check"]), 0)

                # Drifted context file.
                context_path.write_bytes(b'{"@context": {}}\n')
                self.assertEqual(domain_vocabulary.main(["--check"]), 1)
