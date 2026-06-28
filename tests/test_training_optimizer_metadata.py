import unittest
from datetime import date

from tests.test_training_dixon_coles import make_match


class OptimizerMetadataTests(unittest.TestCase):
    def test_fit_records_analytic_jacobian_usage(self):
        from oracle_training.dixon_coles import FitConfig, fit_dixon_coles

        rows = tuple(
            make_match(index, "A" if index % 2 == 0 else "B",
                       "B" if index % 2 == 0 else "A", 1, index % 2)
            for index in range(12)
        )
        candidate = fit_dixon_coles(
            rows,
            cutoff=date(2022, 1, 1),
            version="optimizer-v1",
            config=FitConfig(decay_per_year=0.0, friendly_weight=1.0),
        )

        self.assertEqual(candidate.model["optimizer"]["jacobian"], "analytic")
        self.assertGreater(candidate.model["optimizer"]["evaluations"], 0)


if __name__ == "__main__":
    unittest.main()
