"""Integration tests use synthetic output only; they are NOT GateANN benchmarks."""
import csv
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import experiment as e


FAKE = r'''
import argparse, csv, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('action', choices=['search'])
for flag in ('repo', 'dataset-root', 'tier', 'run-root', 'threads', 'beamwidth', 'k', 'bucket', 'L', 'mem-L', 'cache-budget', 'full-adj-neighbors', 'run-id'):
    p.add_argument('--'+flag, required=True)
a = p.parse_args()
assert (a.threads,a.beamwidth,a.k,a.mem_L,a.cache_budget,a.full_adj_neighbors)==('1','8','10','0','0','32')
t = Path(a.dataset_root)/'formal_1000000'
w = t/'workloads'/a.bucket
prefix = Path(a.run_root)/'indices/gateann/formal_1000000/yfcc'
cmd = [str(Path(a.repo)/'build/tests/search_disk_index_yfcc'),'uint8',str(prefix),'1','8',str(w/'query.u8bin'),str(t/'base.metadata.spmat'),str(w/'query.metadata.spmat'),str(w/'ground_truth.ids.ibin'),'10','l2','pq','8','0','0','32',a.L]
out = Path(a.run_root)/'results/gateann/formal_1000000'/a.bucket/a.run_id
out.mkdir(parents=True, exist_ok=False)
(out/'command.json').write_text(json.dumps(dict(command=cmd,exit_code=0)))
(out/'run.log').write_text(a.L+' 500 0.5 4 0 0 0 0\n')
s = dict(low='.005',medium='.02',high='.1')[a.bucket]
row = dict(system='gateann',tier='formal_1000000',bucket=a.bucket,queries='200',L=a.L,k='10',threads='1',beamwidth='8',qps='500',mean_latency_us='2000',recall_percent='50',mean_ios='4',selectivity_min=s,selectivity_max=s,system_commit='71e87cbf0e25c0400c0109dd25a64a7c4dccc9dd')
for key in ('selectivity_median','index_bytes','elapsed_seconds','peak_rss_kb','p999_latency_us','pre_filter_queries','in_filter_queries','post_filter_queries','filter_false_positives','filter_skips','io_time_us','tunnel_time_us','process_time_us','raw_log'):
    row[key] = ''
with (out/'results.csv').open('w',newline='') as f:
    wr=csv.DictWriter(f,fieldnames=list(row)); wr.writeheader(); wr.writerow(row)
'''


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'adapters').mkdir()
        (self.root / 'adapters/gateann_adapter.py').write_text(FAKE, encoding='utf-8')
        self.cfg = {k: str(self.root / v) for k, v in dict(root='', gateann_repo='system', dataset_root='data', run_root='runs').items()}
        self.folder = self.root / 'experiment'
        self.folder.mkdir()
        jobs = e.make_jobs(42)
        for j in jobs:
            j['run_id'] = 'synthetic-' + j['key']
            j['command'] = e.search_command(self.cfg, j, j['run_id'])
        self.m = dict(status='ready', config=self.cfg, jobs=jobs, seed=42, audit=dict(inputs={}))

    def test_full_pipeline_reuse_and_tamper_detection(self):
        e.run_jobs(self.m, self.folder)
        manifest = e.read_json(self.folder/'manifest.json')
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(len(list((self.root/'runs').rglob('run.log'))), 24)
        with (self.folder/'strategy_measurements.csv').open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 36)
        mixed = [r for r in rows if r['bucket'] == 'mixed_equal_queries']
        self.assertEqual(len(mixed), 9)
        for row in mixed:
            self.assertAlmostEqual(float(row['qps']), 500)
        paths = list((self.root/'runs').rglob('run.log'))
        before = {str(p): p.stat().st_mtime_ns for p in paths}
        e.run_jobs(manifest, self.folder)
        self.assertEqual(before, {str(p): p.stat().st_mtime_ns for p in paths})
        paths[0].write_text('corrupted\n')
        with self.assertRaises(ValueError):
            e.analyze(self.folder)

    def test_old_directory_not_overwritten(self):
        target = e.result_dir(self.cfg, self.m['jobs'][0])
        target.mkdir(parents=True)
        marker = target/'keep.txt'
        marker.write_text('original')
        with self.assertRaises(FileExistsError):
            e.run_jobs(self.m, self.folder)
        self.assertEqual(marker.read_text(), 'original')

    def test_nonzero_exit_leaves_failure_manifest_and_no_summary(self):
        (self.root/'adapters/gateann_adapter.py').write_text('raise SystemExit(7)\n')
        with self.assertRaises(RuntimeError):
            e.run_jobs(self.m, self.folder)
        m = e.read_json(self.folder/'manifest.json')
        self.assertEqual(m['status'], 'failed')
        self.assertEqual(m['jobs'][0]['status'], 'failed')
        self.assertFalse((self.folder/'strategy_summary.csv').exists())

    def test_snapshot_detects_same_size_modification(self):
        path = self.root/'input.bin'
        path.write_bytes(b'abc')
        snap = {str(path): dict(bytes=3, mtime_ns=path.stat().st_mtime_ns, sha256=e.sha(path))}
        path.write_bytes(b'xyz')
        with self.assertRaises(ValueError):
            e.verify_snapshot(snap, full=True)

    def test_resume_rejects_changed_machine_or_thread_environment(self):
        ctx = e.execution_context()
        e.verify_execution_context(ctx)
        for field, value in [('machine_id_sha256', 'different'), ('thread_environment', {'OMP_NUM_THREADS': '2'})]:
            with self.assertRaises(ValueError):
                e.verify_execution_context({**ctx, field: value})

    def test_new_index_file_invalidates_snapshot(self):
        index = self.root/'index'
        index.mkdir()
        original = index/'yfcc_disk.index'
        original.write_bytes(b'abc')
        snapshot = {str(original): dict(bytes=3,mtime_ns=original.stat().st_mtime_ns,sha256=e.sha(original))}
        (index/'yfcc.full_adj.R32').write_bytes(b'new graph')
        with self.assertRaises(ValueError):
            e.verify_snapshot(snapshot)

    def test_fulladj_cache_required_before_measurement(self):
        index = self.root/'index'
        index.mkdir()
        (index/'yfcc_disk.index').write_bytes(b'abc')
        with self.assertRaises(FileNotFoundError):
            e.index_files(index)
        (index/'yfcc.full_adj.R32').write_bytes(b'graph')
        self.assertEqual(len(e.index_files(index)), 2)

    def test_capture_preserves_interrupted_and_existing_logs(self):
        log = self.folder/'adapter.log'
        def interrupted(*args, **kwargs):
            kwargs['stdout'].write('partial diagnostic\n')
            raise KeyboardInterrupt()
        with mock.patch.object(e.subprocess, 'run', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                e.capture(['irrelevant'], log)
        self.assertEqual(log.read_text(), 'partial diagnostic\n')
        with self.assertRaises(FileExistsError):
            e.capture([sys.executable, '-c', "print('replacement')"], log)
        self.assertEqual(log.read_text(), 'partial diagnostic\n')

    def test_strict_csv_and_raw_rows(self):
        job = self.m['jobs'][0]
        e.capture(job['command'])
        folder = e.result_dir(self.cfg, job)
        raw = folder/'run.log'
        original = raw.read_text()
        for bad in (original+'640 100 0.1 2 0 0 0 0\n',
                    f"{job['L']} 500 0.5 4 nan inf -1 0\n"):
            raw.write_text(bad)
            with self.assertRaises(ValueError):
                e.load_result(self.cfg, job)
        raw.write_text(original)
        path = folder/'results.csv'
        original = path.read_text()
        lines = original.splitlines()
        for bad in ('qps,'+lines[0]+'\nBROKEN,'+lines[1]+'\n', original.rstrip() + ',EXTRA\n'):
            path.write_text(bad)
            with self.assertRaises(ValueError):
                e.load_result(self.cfg, job)

    def test_labels_csv_duplicate_headers_rejected(self):
        path = self.root/'labels.csv'
        path.write_text('selectivity,query_count,selectivity\nBAD,200,0.005\n')
        with self.assertRaises(ValueError):
            e.read_csv_strict(path, {'selectivity','query_count'})


if __name__ == '__main__':
    unittest.main()
