import unittest


class TrainingTaxonomyTests(unittest.TestCase):
    def test_known_and_unknown_tournaments(self):
        from oracle_training.taxonomy import classify_tournament
        from oracle_training.types import TournamentCategory

        self.assertEqual(classify_tournament("FIFA World Cup"), TournamentCategory.WORLD_CUP)
        self.assertEqual(
            classify_tournament("FIFA World Cup qualification"),
            TournamentCategory.WORLD_CUP_QUALIFIER,
        )
        self.assertEqual(classify_tournament("Friendly"), TournamentCategory.FRIENDLY)
        self.assertEqual(
            classify_tournament("Unknown Invitational"), TournamentCategory.OTHER
        )

    def test_successor_states_are_not_silently_merged(self):
        from oracle_training.taxonomy import TeamAliasMap

        aliases = TeamAliasMap()
        self.assertEqual(aliases.resolve("Serbia"), "Serbia")
        self.assertEqual(
            aliases.resolve("Serbia and Montenegro"), "Serbia and Montenegro"
        )
        self.assertNotEqual(
            aliases.resolve("Serbia"), aliases.resolve("Serbia and Montenegro")
        )
        self.assertTrue(aliases.version)


if __name__ == "__main__":
    unittest.main()
