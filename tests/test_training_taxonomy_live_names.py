import unittest


class LiveTournamentTaxonomyTests(unittest.TestCase):
    def test_reviewed_live_source_names_have_explicit_categories(self):
        from oracle_training.taxonomy import classify_tournament
        from oracle_training.types import TournamentCategory

        expected = {
            "Copa América": TournamentCategory.CONTINENTAL_FINAL,
            "Oceania Nations Cup": TournamentCategory.CONTINENTAL_FINAL,
            "Gold Cup qualification": TournamentCategory.CONTINENTAL_QUALIFIER,
            "CONCACAF Nations League qualification": TournamentCategory.NATIONS_LEAGUE,
            "AFF Championship": TournamentCategory.CONTINENTAL_FINAL,
            "AFF Championship qualification": TournamentCategory.CONTINENTAL_QUALIFIER,
        }
        for name, category in expected.items():
            with self.subTest(name=name):
                self.assertEqual(classify_tournament(name), category)


if __name__ == "__main__":
    unittest.main()
