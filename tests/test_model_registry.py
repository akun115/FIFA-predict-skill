import json
import math
import tempfile
import unittest
from pathlib import Path


def model(version="test-v1"):
    return {
        "schema_version": 1, "version": version, "training_cutoff": "2025-12-31",
        "intercept": math.log(1.3), "home_advantage": 0.1, "rho": -0.05,
        "elo_coefficient": 0.0, "attack": {"A": 0.0, "B": 0.0},
        "defense": {"A": 0.0, "B": 0.0},
        "category_effects": {"other": 0.0},
        "min_expected_goals": 0.1, "max_expected_goals": 5.0,
    }


class ModelRegistryTests(unittest.TestCase):
    def setUp(self):
        from oracle_training.registry import ModelRegistry

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = ModelRegistry(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_gates_do_not_create_current_pointer(self):
        from oracle_training.registry import PromotionRejected

        self.registry.save_candidate(model(), {"normalized_sha256": "abc"}, {"gates": {"log_loss": False}})
        with self.assertRaises(PromotionRejected):
            self.registry.promote("test-v1", confirm=True)
        self.assertFalse((self.root / "current.json").exists())

    def test_successful_promotion_is_loadable(self):
        path = self.registry.save_candidate(
            model(), {"normalized_sha256": "abc"}, {"gates": {"log_loss": True, "integrity": True}}
        )
        self.assertEqual(self.registry.status("test-v1")["status"], "candidate")
        self.registry.promote("test-v1", confirm=True)
        self.assertEqual(self.registry.status()["version"], "test-v1")
        self.assertEqual(self.registry.load_current().version, "test-v1")
        self.assertTrue((path / "checksum.sha256").is_file())

    def test_corruption_is_rejected(self):
        from oracle_training.registry import ArtifactIntegrityError

        path = self.registry.save_candidate(
            model(), {"normalized_sha256": "abc"}, {"gates": {"integrity": True}}
        )
        (path / "model.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ArtifactIntegrityError):
            self.registry.validate("test-v1")


if __name__ == "__main__":
    unittest.main()
