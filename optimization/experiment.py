#!/usr/bin/env python3
"""GateANN workload-level budget experiment; Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import random
import re
import shlex
import statistics
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from adaptive_budget import workload_budget

MATRIX = {'low': (320, 480, 640), 'medium': (320, 480, 640), 'high': (320, 640)}
ADAPTIVE = {'low': 640, 'medium': 480, 'high': 320}
METRICS = ('recall_percent', 'latency_ms', 'qps', 'mean_ios')
PIN = '71e87cbf0e25c0400c0109dd25a64a7c4dccc9dd'
COURSE_COLUMNS = set(('system tier bucket queries selectivity_min selectivity_median selectivity_max '
                      'L k threads beamwidth system_commit index_bytes elapsed_seconds peak_rss_kb '
                      'qps mean_latency_us p999_latency_us recall_percent mean_ios pre_filter_queries '
                      'in_filter_queries post_filter_queries filter_false_positives filter_skips '
                      'io_time_us tunnel_time_us process_time_us raw_log').split())


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def make_jobs(seed):
    rng = random.Random(seed)
    jobs = []
    for repeat in (1, 2, 3):
        block = [dict(bucket=b, L=l, repeat=repeat, key=f'{b}-L{l}-r{repeat}', status='pending')
                 for b, values in MATRIX.items() for l in values]
        rng.shuffle(block)
        jobs.extend(block)
    return jobs


def finite(value, name, low=0, high=math.inf):
    x = float(value)
    if not math.isfinite(x) or not low <= x <= high:
        raise ValueError(f'invalid {name}: {value}')
    return x


def validate_row(row, job):
    expected = dict(system='gateann', tier='formal_1000000', bucket=job['bucket'],
                    L=str(job['L']), queries='200', k='10', threads='1', beamwidth='8')
    for key, val in expected.items():
        if row.get(key) != val:
            raise ValueError(f'CSV {key}: expected {val}, got {row.get(key)}')
    qps = finite(row['qps'], 'qps', low=1e-300)
    latency = finite(row['mean_latency_us'], 'mean_latency_us', low=1e-300)
    if not math.isclose(latency, 1e6 / qps, rel_tol=1e-6):
        raise ValueError('latency definition differs from verified course adapter (1e6/qps)')
    lo = finite(row['selectivity_min'], 'selectivity_min', high=1)
    hi = finite(row['selectivity_max'], 'selectivity_max', high=1)
    if lo > hi or workload_budget([lo, hi]) != ADAPTIVE[job['bucket']]:
        raise ValueError('selectivity range inconsistent with workload policy')
    return dict(queries=200, recall_percent=finite(row['recall_percent'], 'recall', high=100),
                latency_ms=latency / 1000, qps=qps,
                mean_ios=finite(row['mean_ios'], 'logical IO'))


def stats(values):
    return dict(n=len(values), median=statistics.median(values), min=min(values),
                max=max(values), range=max(values)-min(values))


def mix(rows):
    n = sum(r['queries'] for r in rows)
    out = {m: sum(r[m] * r['queries'] for r in rows) / n for m in METRICS if m != 'qps'}
    out.update(queries=n, qps=n / sum(r['queries'] / r['qps'] for r in rows))
    return out


def capture(cmd, log=None):
    if log:
        # Open exclusively before starting the process. Diagnostics survive interruption.
        with Path(log).open('x', encoding='utf-8') as stream:
            p = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT,
                               env={**os.environ, 'PYTHONUNBUFFERED': '1'})
        output = Path(log).read_text(encoding='utf-8', errors='replace')
    else:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding='utf-8', errors='replace')
        output = p.stdout
    if p.returncode:
        raise RuntimeError(f'exit {p.returncode}: {shlex.join(map(str, cmd))}; see {log or output}')
    return output


def read_csv_strict(path, required):
    try:
        with Path(path).open(newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f, strict=True)
            header = next(reader, [])
            if (not header or any(not h.strip() for h in header) or len(set(header)) != len(header)
                    or not required.issubset(header)):
                raise ValueError(f'invalid/duplicate/missing CSV header: {path}')
            rows = []
            for values in reader:
                if len(values) != len(header):
                    raise ValueError(f'CSV row width mismatch: {path}')
                rows.append(dict(zip(header, values)))
            return rows
    except csv.Error as err:
        raise ValueError(f'invalid CSV quoting: {path}: {err}') from err


def index_files(index):
    for name in ('yfcc_disk.index', 'yfcc.full_adj.R32'):
        if not (index/name).is_file() or (index/name).stat().st_size == 0:
            raise FileNotFoundError(f'missing/empty {index/name}; see START_HERE.md cache preparation')
    return sorted(p for p in index.glob('yfcc*') if p.is_file())


def git(repo, *args):
    return capture(['git', '-C', str(repo), *args]).strip()


def execution_context():
    machine_file = Path('/etc/machine-id')
    machine_id = machine_file.read_bytes() if machine_file.is_file() else platform.node().encode()
    return dict(platform=platform.platform(), cpu_count=os.cpu_count(),
                machine_id_sha256=hashlib.sha256(machine_id).hexdigest(),
                thread_environment={k: os.environ.get(k) for k in
                                    ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')})


def verify_execution_context(expected):
    if execution_context() != expected:
        raise ValueError('machine/platform/thread environment changed; start a new experiment')


def search_command(cfg, job, run_id):
    return [sys.executable, str(Path(cfg['root']) / 'adapters/gateann_adapter.py'), 'search',
            '--repo', cfg['gateann_repo'], '--dataset-root', cfg['dataset_root'], '--tier', 'formal',
            '--run-root', cfg['run_root'], '--threads', '1', '--beamwidth', '8', '--k', '10',
            '--bucket', job['bucket'], '--L', str(job['L']), '--mem-L', '0', '--cache-budget', '0',
            '--full-adj-neighbors', '32', '--run-id', run_id]


def raw_command(cfg, job):
    tier = Path(cfg['dataset_root']) / 'formal_1000000'
    work = tier / 'workloads' / job['bucket']
    prefix = Path(cfg['run_root']) / 'indices/gateann/formal_1000000/yfcc'
    return [str(Path(cfg['gateann_repo']) / 'build/tests/search_disk_index_yfcc'), 'uint8',
            str(prefix), '1', '8', str(work / 'query.u8bin'), str(tier / 'base.metadata.spmat'),
            str(work / 'query.metadata.spmat'), str(work / 'ground_truth.ids.ibin'), '10', 'l2', 'pq',
            '8', '0', '0', '32', str(job['L'])]


def bin_header(path, fmt):
    with path.open('rb') as f:
        data = f.read(struct.calcsize(fmt))
    return struct.unpack(fmt, data)


def inspect_inputs(cfg):
    """Validate actual files, rather than assume the bucket name encodes selectivity."""
    root, system = Path(cfg['root']), Path(cfg['gateann_repo'])
    tier = Path(cfg['dataset_root']) / 'formal_1000000'
    if bin_header(tier / 'base.u8bin', '<II') != (1000000, 192):
        raise ValueError('expected formal 1M x 192D base')
    if (tier / 'base.u8bin').stat().st_size != 8 + 1000000 * 192:
        raise ValueError('truncated or wrong uint8 base')
    base_n, meta_cols, _ = bin_header(tier / 'base.metadata.spmat', '<qqq')
    if base_n != 1000000:
        raise ValueError('base metadata row mismatch')
    files = [tier / f for f in ('base.u8bin', 'base.metadata.spmat', 'base.labels.txt')]
    summaries = {}
    for bucket in MATRIX:
        w = tier / 'workloads' / bucket
        for name in ('query.u8bin', 'query.metadata.spmat', 'query_filters.csv', 'labels.csv',
                     'ground_truth.ids.ibin', 'ground_truth.diskann.bin'):
            if not (w / name).is_file():
                raise FileNotFoundError(w / name)
            files.append(w / name)
        if bin_header(w / 'query.u8bin', '<II') != (200, 192) or (w / 'query.u8bin').stat().st_size != 38408:
            raise ValueError(f'{bucket}: expected 200 x 192D uint8 queries')
        gn, gk = bin_header(w / 'ground_truth.ids.ibin', '<II')
        if gn != 200 or gk < 10 or (w / 'ground_truth.ids.ibin').stat().st_size != 8 + gn*gk*4:
            raise ValueError(f'{bucket}: invalid ground truth')
        if bin_header(w / 'query.metadata.spmat', '<qqq') != (200, meta_cols, 200):
            raise ValueError(f'{bucket}: expected single-label query metadata')
        rows = read_csv_strict(w / 'labels.csv', {'selectivity', 'query_count'})
        sels = [finite(r['selectivity'], 'selectivity', high=1) for r in rows]
        counts = [int(r['query_count']) for r in rows]
        if not counts or any(c <= 0 for c in counts) or sum(counts) != 200:
            raise ValueError(f'{bucket}: labels.csv query_count must sum to 200')
        selected = workload_budget(sels)
        if selected != ADAPTIVE[bucket]:
            raise ValueError(f'{bucket}: actual selectivities require L={selected}')
        summaries[bucket] = dict(queries=sum(counts), selectivity_min=min(sels), selectivity_max=max(sels),
                                 selected_L=selected, label_count=len(rows))
    index = Path(cfg['run_root']) / 'indices/gateann/formal_1000000'
    files += index_files(index)
    files += [root / f for f in ('adapters/gateann_adapter.py', 'adapters/_common.py',
                                 'adapters/versions.json', 'config/experiments.env')]
    files += [system / 'build/tests/search_disk_index_yfcc', system / 'build/CMakeCache.txt']
    files += sorted((root / 'patches').glob('*aio*compat*.patch'))
    files += [Path(__file__).resolve(), Path(__file__).with_name('adaptive_budget.py').resolve()]
    return summaries, sorted(set(files))


def preflight(cfg, folder, full=True):
    if platform.system() != 'Linux':
        raise RuntimeError('real preflight/run requires Linux; plan and unit tests work on Windows')
    root, system = Path(cfg['root']), Path(cfg['gateann_repo'])
    adapter = root / 'adapters/gateann_adapter.py'
    help_text = capture([sys.executable, str(adapter), 'search', '--help'], folder / 'adapter-help.txt')
    for flag in ('--L', '--mem-L', '--cache-budget', '--full-adj-neighbors', '--run-id'):
        if flag not in help_text:
            raise ValueError(f'local adapter lacks {flag}')
    capture([sys.executable, str(adapter), 'doctor', '--repo', str(system),
             '--dataset-root', cfg['dataset_root'], '--tier', 'formal'], folder / 'doctor.txt')
    if git(system, 'rev-parse', 'HEAD') != PIN:
        raise ValueError('GateANN differs from course-pinned commit')
    summaries, files = inspect_inputs(cfg)
    for bucket, values in MATRIX.items():
        for l in values:
            job = dict(bucket=bucket, L=l)
            cmd = search_command(cfg, job, 'preflight-only') + ['--dry-run']
            text = capture(cmd, folder / f'dry-{bucket}-{l}.txt')
            if shlex.join(raw_command(cfg, job)) not in text.splitlines():
                raise ValueError('local adapter command differs from audited positional CLI')
    snapshot = {str(p): dict(bytes=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns,
                            sha256=sha(p) if full else None) for p in files}
    env = dict(platform=platform.platform(), python=sys.version, cpu_count=os.cpu_count(),
               course_commit=git(root, 'rev-parse', 'HEAD'), course_status=git(root, 'status', '--short'),
               gateann_commit=git(system, 'rev-parse', 'HEAD'), gateann_status=git(system, 'status', '--short'),
               gateann_diff_sha256=hashlib.sha256(git(system, 'diff', 'HEAD').encode()).hexdigest(),
               thread_environment={k: os.environ.get(k) for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')})
    for cmd, name in [(['uname', '-a'], 'uname'), (['lscpu'], 'lscpu'), (['free', '-h'], 'memory'),
                      (['lsblk', '-d', '-o', 'NAME,MODEL,SIZE,ROTA,TRAN'], 'disks')]:
        try:
            env[name] = capture(cmd)
        except (OSError, RuntimeError) as e:
            env[name] = str(e)
    return dict(inputs=snapshot, workloads=summaries, environment=env, execution_context=execution_context())


def verify_snapshot(snapshot, full=False):
    index_dirs = {Path(name).parent for name in snapshot if Path(name).name == 'yfcc_disk.index'}
    for parent in index_dirs:
        expected = {Path(name) for name in snapshot if Path(name).parent == parent and Path(name).name.startswith('yfcc')}
        actual = {p for p in parent.glob('yfcc*') if p.is_file()}
        if actual != expected:
            raise ValueError(f'index file inventory changed: {parent}')
    for name, record in snapshot.items():
        p = Path(name)
        if not p.is_file() or p.stat().st_size != record['bytes'] or p.stat().st_mtime_ns != record['mtime_ns']:
            raise ValueError(f'input changed or missing: {name}')
        if full and sha(p) != record['sha256']:
            raise ValueError(f'input SHA256 changed: {name}')


def result_dir(cfg, job):
    return Path(cfg['run_root']) / 'results/gateann/formal_1000000' / job['bucket'] / job['run_id']


def load_result(cfg, job):
    folder = result_dir(cfg, job)
    record = read_json(folder / 'command.json')
    if record.get('exit_code') != 0 or record.get('command') != raw_command(cfg, job):
        raise ValueError(f'{folder}: failed or incompatible raw command')
    rows = read_csv_strict(folder / 'results.csv', COURSE_COLUMNS)
    if len(rows) != 1:
        raise ValueError(f'{folder}: expected exactly one result row')
    metrics = validate_row(rows[0], job)
    if rows[0].get('system_commit') != PIN:
        raise ValueError('result system_commit mismatch')
    text = (folder / 'run.log').read_text(encoding='utf-8')
    raw = []
    for line in text.splitlines():
        try:
            values = list(map(float, line.split()))
        except ValueError:
            continue
        if len(values) == 8:
            raw.append(values)
    if len(raw) != 1:
        raise ValueError('expected one eight-column GateANN numeric row in raw log')
    if raw[0][0] != job['L'] or any(not math.isfinite(v) or v < 0 for v in raw[0]):
        raise ValueError('raw GateANN row has incorrect L or invalid diagnostics')
    for actual, expected in zip((metrics['qps'], metrics['recall_percent'], metrics['mean_ios']),
                                (raw[0][1], raw[0][2]*100, raw[0][3])):
        if not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError('CSV differs from raw GateANN output')
    files = {str(folder / name): sha(folder / name) for name in ('results.csv', 'command.json', 'run.log')}
    return metrics, files


def run_jobs(manifest, folder):
    cfg = manifest['config']
    manifest['status'] = 'running'
    save_json(folder / 'manifest.json', manifest)
    for job in manifest['jobs']:
        if job['status'] == 'complete':
            metrics, hashes = load_result(cfg, job)
            if hashes != job['result_sha256'] or metrics != job['metrics']:
                raise ValueError(f"completed result changed: {job['key']}")
            continue
        verify_snapshot(manifest['audit']['inputs'])
        target = result_dir(cfg, job)
        if target.exists() or (folder / f"{job['key']}.adapter.log").exists():
            raise FileExistsError(f'will not overwrite incomplete/old result: {target}; use a new experiment ID')
        job.update(status='running', started_utc=now())
        save_json(folder / 'manifest.json', manifest)
        print(f"[{job['repeat']}/3] {job['bucket']} L={job['L']}", flush=True)
        started = time.perf_counter()
        try:
            capture(job['command'], folder / f"{job['key']}.adapter.log")
            metrics, hashes = load_result(cfg, job)
            verify_snapshot(manifest['audit']['inputs'])
            job.update(status='complete', finished_utc=now(), metrics=metrics, result_sha256=hashes,
                       process_wall_seconds=time.perf_counter()-started)
        except BaseException as e:
            job.update(status='failed', error=f'{type(e).__name__}: {e}')
            manifest['status'] = 'failed'
            save_json(folder / 'manifest.json', manifest)
            raise
        save_json(folder / 'manifest.json', manifest)
    manifest.update(status='complete', finished_utc=now())
    save_json(folder / 'manifest.json', manifest)
    analyze(folder)


def write_csv(path, rows):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    content = out.getvalue()
    if path.exists():
        if path.read_text(encoding='utf-8').replace('\r\n', '\n') != content.replace('\r\n', '\n'):
            raise FileExistsError(f'refusing to replace different derived output: {path}')
        return
    with path.open('x', encoding='utf-8', newline='') as f:
        f.write(content)


def analyze(folder):
    m = read_json(folder / 'manifest.json')
    expected = {(j['bucket'], j['L'], j['repeat']) for j in make_jobs(m['seed'])}
    actual = [(j['bucket'], j['L'], j['repeat']) for j in m['jobs']]
    if m['status'] != 'complete' or len(actual) != 24 or set(actual) != expected:
        raise ValueError('analysis requires exactly 24 complete unique measurements')
    observations, lookup = [], {}
    for j in m['jobs']:
        if j['status'] != 'complete':
            raise ValueError('incomplete measurement')
        metrics, hashes = load_result(m['config'], j)
        if hashes != j['result_sha256'] or metrics != j['metrics']:
            raise ValueError('measurement changed after completion')
        lookup[(j['bucket'], j['L'], j['repeat'])] = metrics
        observations.append(dict(bucket=j['bucket'], L=j['L'], repeat=j['repeat'],
                                 source_run_id=j['run_id'], **metrics))
    sweep = []
    for b, values in MATRIX.items():
        for l in values:
            for metric in METRICS:
                sweep.append(dict(bucket=b, L=l, metric=metric,
                                  **stats([lookup[(b, l, r)][metric] for r in (1, 2, 3)])))
    strategy_rows, summary, deltas = [], [], []
    for strategy in ('fixed320', 'fixed640', 'adaptive'):
        per_repeat = {}
        for r in (1, 2, 3):
            selected = []
            for b in MATRIX:
                l = ADAPTIVE[b] if strategy == 'adaptive' else int(strategy[5:])
                values = lookup[(b, l, r)]
                selected.append(values)
                per_repeat[(b, r)] = values
                strategy_rows.append(dict(strategy=strategy, bucket=b, repeat=r, L=l,
                                          source_key=f'{b}-L{l}-r{r}', observation_reused=True, **values))
            per_repeat[('mixed_equal_queries', r)] = mix(selected)
            strategy_rows.append(dict(strategy=strategy, bucket='mixed_equal_queries', repeat=r, L='',
                                      source_key='derived_from_three_buckets', observation_reused=True,
                                      **per_repeat[('mixed_equal_queries', r)]))
        for b in (*MATRIX, 'mixed_equal_queries'):
            for metric in METRICS:
                summary.append(dict(strategy=strategy, bucket=b, metric=metric,
                                    **stats([per_repeat[(b, r)][metric] for r in (1, 2, 3)])))
        if strategy != 'fixed320':
            for b in MATRIX:
                for metric in METRICS:
                    values = [per_repeat[(b, r)][metric] - lookup[(b, 320, r)][metric] for r in (1, 2, 3)]
                    deltas.append(dict(strategy=strategy, bucket=b, metric=metric,
                                       definition='strategy_minus_fixed320_same_repeat', **stats(values)))
    for name, rows in [('measurements.csv', observations), ('sweep_summary.csv', sweep),
                        ('strategy_measurements.csv', strategy_rows), ('strategy_summary.csv', summary),
                        ('paired_deltas.csv', deltas)]:
        write_csv(folder / name, rows)
    print(f'Validated 24 measurements; summaries: {folder}', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('plan', 'check', 'run', 'resume', 'analyze'))
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--gateann-repo', type=Path)
    p.add_argument('--dataset-root', type=Path)
    p.add_argument('--run-root', type=Path)
    p.add_argument('--experiment-id')
    p.add_argument('--seed', type=int, default=20261110)
    p.add_argument('--experiment-dir', type=Path, help='required for resume/analyze')
    a = p.parse_args()
    if a.action in ('resume', 'analyze'):
        if not a.experiment_dir:
            p.error('--experiment-dir is required')
        folder = a.experiment_dir.resolve()
        if a.action == 'analyze':
            analyze(folder)
        else:
            m = read_json(folder / 'manifest.json')
            if platform.system() != 'Linux':
                raise RuntimeError('resume requires Linux')
            verify_snapshot(m['audit']['inputs'], full=True)
            verify_execution_context(m['audit']['execution_context'])
            run_jobs(m, folder)
        return
    root = a.root.resolve()
    cfg = dict(root=str(root), gateann_repo=str((a.gateann_repo or root/'systems/GateANN-public').resolve()),
               dataset_root=str((a.dataset_root or root/'datasets/yfcc_course_v1').resolve()),
               run_root=str((a.run_root or root/'course_runs').resolve()))
    eid = a.experiment_id or ('budget-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', eid):
        raise ValueError('experiment ID must be a safe single directory name')
    jobs = make_jobs(a.seed)
    for j in jobs:
        j['run_id'] = eid + '-' + j['key']
        j['command'] = search_command(cfg, j, j['run_id'])
    manifest = dict(schema_version=1, kind='workload_level_budget_selection',
                    status='planned', created_utc=now(), seed=a.seed, experiment_id=eid, config=cfg,
                    policy=dict(low=640, medium=480, high=320, thresholds_fraction=[.01, .05]),
                    timing='query QPS from GateANN; latency_ms=1000/qps; wall time diagnostic only',
                    cache_protocol='no OS cache drop; input hashing before timing; singleton L processes; seeded block shuffle',
                    repeats=3, jobs=jobs)
    if a.action == 'plan':
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    folder = Path(cfg['run_root']) / 'optimization' / eid
    folder.mkdir(parents=True, exist_ok=False)
    try:
        print(f'Preflight and input checks: {folder}', flush=True)
        manifest['audit'] = preflight(cfg, folder, full=a.action == 'run')
        manifest['status'] = 'checked' if a.action == 'check' else 'ready'
        save_json(folder / 'manifest.json', manifest)
        if a.action == 'run':
            run_jobs(manifest, folder)
        else:
            print(f'CHECK PASS (no search executed): {folder}')
    except BaseException as e:
        if not (folder / 'manifest.json').exists():
            manifest.update(status='preflight_failed', error=f'{type(e).__name__}: {e}')
            save_json(folder / 'manifest.json', manifest)
        raise


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, struct.error) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(2)
