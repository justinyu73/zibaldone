import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from routers import settings as settings_router


class SetupReadinessTest(unittest.TestCase):
    def test_existing_vault_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = list(root.iterdir())
            with patch.object(settings_router, "app_state_model_options", return_value={"translate": [], "summary": []}), \
                 patch.object(settings_router, "_local_asr_runtime_readiness", return_value={"ready": False}):
                result = settings_router.app_setup_readiness(str(root))

            self.assertTrue(result["ok"])
            self.assertTrue(result["checks_are_read_only"])
            self.assertEqual(result["vault"]["exists"], True)
            self.assertEqual(result["vault"]["is_directory"], True)
            self.assertEqual(result["vault"]["readable"], True)
            self.assertEqual(result["vault"]["writable"], True)
            self.assertEqual(list(root.iterdir()), before)

    def test_missing_vault_is_reported_without_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with patch.object(settings_router, "app_state_model_options", return_value={"translate": [], "summary": []}), \
                 patch.object(settings_router, "_local_asr_runtime_readiness", return_value={"ready": False}):
                result = settings_router.app_setup_readiness(str(missing))

            self.assertFalse(result["vault"]["exists"])
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
