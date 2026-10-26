#!/usr/bin/env python3
"""Multi-seed regression runner: launches the cocotb/pyuvm test per seed in parallel,
parses results.txt + coverage.yml, writes regression_summary.txt, exits non-zero on any failure.
Usage: python3 run_regression.py [--seeds 8] [--n 400] [--rtl ../rtl]"""
import argparse, concurrent.futures as cf, os, shutil, subprocess, sys, time
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--seeds", type=int, default=8)
ap.add_argument("--n", type=int, default=400)
ap.add_argument("--rtl", default=os.path.join(HERE, "..", "rtl"))
a = ap.parse_args()


def run(seed):
    wd = os.path.join(HERE, "regress", f"seed{seed}")
    shutil.rmtree(wd, ignore_errors=True); os.makedirs(wd)
    for f in ("Makefile", "mips_env.py", "mips_model.py", "test_mips.py", "program.mem"):
        shutil.copy(os.path.join(HERE, f), wd)
    env = dict(os.environ, SEED=str(seed), N_RANDOM=str(a.n), RTL_DIR=os.path.abspath(a.rtl))
    t0 = time.time()
    r = subprocess.run(["make", "-C", wd], env=env, capture_output=True, text=True)
    res = dict(l.split(" ", 1) for l in open(os.path.join(wd, "results.txt")).read().splitlines()
               if l.split(" ", 1)[0] in ("programs", "cycles", "mismatches", "failing_programs")) \
        if os.path.exists(os.path.join(wd, "results.txt")) else {}
    cov = yaml.safe_load(open(os.path.join(wd, "coverage.yml"))) if os.path.exists(os.path.join(wd, "coverage.yml")) else {}
    return seed, r.returncode == 0, res, cov, time.time() - t0


t0 = time.time()
with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
    results = list(ex.map(run, range(1, a.seeds + 1)))
wall = time.time() - t0

# merge functional coverage: a bin is hit if any seed hit it
merged = {}
for _, _, _, cov, _ in results:
    for pt, d in cov.items():
        if not isinstance(d, dict) or "bins:_hits" not in d:
            continue
        m = merged.setdefault(pt, {})
        for b, h in d["bins:_hits"].items():
            m[b] = m.get(b, 0) + (h or 0)
hit = sum(1 for p in merged.values() for h in p.values() if h)
size = sum(len(p) for p in merged.values())
lines = [f"{'seed':>4} {'status':6} {'programs':>8} {'cycles':>8} {'mismatch':>8} {'time_s':>6}"]
for s, ok, r, _, t in results:
    lines.append(f"{s:>4} {'PASS' if ok else 'FAIL':6} {r.get('programs','?'):>8} {r.get('cycles','?'):>8} {r.get('mismatches','?'):>8} {t:6.1f}")
tot_prog = sum(int(r.get('programs', 0)) for _, _, r, _, _ in results)
tot_cyc = sum(int(r.get('cycles', 0)) for _, _, r, _, _ in results)
lines.append(f"TOTAL programs={tot_prog} cycles_compared={tot_cyc} wall={wall:.1f}s")
lines.append(f"MERGED FUNCTIONAL COVERAGE: {hit}/{size} bins = {100*hit/max(size,1):.1f}%")
for pt, p in sorted(merged.items()):
    miss = [b for b, h in p.items() if not h]
    if miss:
        lines.append(f"  hole {pt}: {miss}")
open(os.path.join(HERE, "regression_summary.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
sys.exit(0 if all(ok for _, ok, *_ in results) else 1)
