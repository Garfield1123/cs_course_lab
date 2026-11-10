import csv
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import adaptive_budget as budget
import experiment


class BudgetTests(unittest.TestCase):
    def test_thresholds_and_invalid_units(self):
        for s, expected in [(0, 640), (.00999, 640), (.01, 480), (.04999, 480), (.05, 320), (1, 320)]:
            self.assertEqual(budget.choose_budget(s), expected)
        for s in [-1, 1.1, float('nan'), float('inf'), True]:
            with self.assertRaises(ValueError):
                budget.choose_budget(s)

    def test_cross_threshold_workload_is_rejected(self):
        self.assertEqual(budget.workload_budget([.01765, .04995]), 480)
        for values in [[], [.009, .02]]:
            with self.assertRaises(ValueError):
                budget.workload_budget(values)

    def test_unique_matrix_reuses_baseline(self):
        jobs = experiment.make_jobs(42)
        self.assertEqual(len(jobs), 24)
        self.assertEqual(len({(j['bucket'], j['L'], j['repeat']) for j in jobs}), 24)
        self.assertEqual(sum(j['L'] == 480 for j in jobs), 6)
        self.assertEqual(jobs, experiment.make_jobs(42))
        self.assertEqual({j['bucket'] for j in jobs[:8]}, {'low', 'medium', 'high'})

    def test_csv_units_and_missing_or_nonfinite_metrics(self):
        row = dict(system='gateann', tier='formal_1000000', bucket='low', queries='200',
                   L='320', k='10', threads='1', beamwidth='8', qps='500',
                   mean_latency_us='2000', recall_percent='34.3', mean_ios='4.38',
                   selectivity_min='.0025', selectivity_max='.00851')
        got = experiment.validate_row(row, {'bucket': 'low', 'L': 320})
        self.assertEqual(got['latency_ms'], 2)
        for field, bad in [('qps', 'nan'), ('qps', '0'), ('recall_percent', '101'),
                           ('mean_ios', '-1'), ('L', '480'), ('queries', '199'),
                           ('mean_latency_us', '999')]:
            with self.assertRaises(ValueError, msg=field):
                experiment.validate_row({**row, field: bad}, {'bucket': 'low', 'L': 320})

    def test_mixed_qps_uses_total_query_time(self):
        rows = [dict(queries=200, qps=100, latency_ms=10, recall_percent=50, mean_ios=2),
                dict(queries=200, qps=200, latency_ms=5, recall_percent=100, mean_ios=4)]
        got = experiment.mix(rows)
        self.assertAlmostEqual(got['qps'], 400 / 3)
        self.assertEqual(got['latency_ms'], 7.5)
        self.assertEqual(got['recall_percent'], 75)
        self.assertEqual(got['mean_ios'], 3)

    def test_range_is_max_minus_min(self):
        self.assertEqual(experiment.stats([8, 1, 3]), {'n': 3, 'median': 3, 'min': 1, 'max': 8, 'range': 7})


if __name__ == '__main__':
    unittest.main()
