import tempfile
import unittest
from pathlib import Path


class EntityRegistryTests(unittest.TestCase):
    def setUp(self):
        from football_data.entities import EntityRegistry

        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "hub.sqlite3"
        self.registry = EntityRegistry(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_provider_id_and_normalized_name_resolve(self):
        brazil = self.registry.create("team", "Brazil")
        self.registry.add_alias(brazil, "football-data.org", "764", "Brazil")
        self.assertEqual(
            self.registry.resolve(
                "team", provider="football-data.org", provider_id="764"
            ),
            brazil,
        )
        self.assertEqual(self.registry.resolve("team", name="  BRAZIL "), brazil)

    def test_ambiguous_alias_is_rejected(self):
        from football_data.entities import EntityAmbiguityError

        first = self.registry.create("team", "United A")
        second = self.registry.create("team", "United B")
        self.registry.add_alias(first, "manual", "1", "United")
        self.registry.add_alias(second, "manual", "2", "United")
        with self.assertRaises(EntityAmbiguityError):
            self.registry.resolve("team", name="United")

    def test_resolve_does_not_create_unknown_entity(self):
        self.assertIsNone(self.registry.resolve("team", name="Unknown"))
        self.assertEqual(self.registry.count(), 0)


if __name__ == "__main__":
    unittest.main()
