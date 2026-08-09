import json
from io import StringIO
from django.core.management import call_command
from django.test import TestCase

class FloppyPreflightTest(TestCase):
    def test_preflight_json(self):
        """Ensure floppy_preflight returns valid JSON with expected keys."""
        out = StringIO()
        call_command("floppy_preflight", "--json", stdout=out)
        
        output = out.getvalue().strip()
        data = json.loads(output)
        
        self.assertIn("db_path", data)
        self.assertIn("integrity_ok", data)
        self.assertIn("integrity_error", data)
        self.assertIn("needs_migration", data)
        self.assertIn("unapplied_count", data)
        
        # In a test environment, integrity should be ok and migrations applied
        self.assertTrue(data["integrity_ok"])
        self.assertFalse(data["needs_migration"])
        self.assertEqual(data["unapplied_count"], 0)

    def test_preflight_text(self):
        """Ensure floppy_preflight returns text format by default."""
        out = StringIO()
        call_command("floppy_preflight", stdout=out)
        
        output = out.getvalue().strip()
        self.assertIn("db_path:", output)
        self.assertIn("integrity_ok: True", output)
