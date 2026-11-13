#!/usr/bin/env python3
"""Tabulate cost vs library size from scripts/scaling_sweep.sh output.
  scripts/scaling_report.py <label> [outdir]   metric: cold_s | warm_med_s | warm_q | cold_q | bytes
"""
import csv, glob, os, re, sys
label = sys.argv[1]
d = sys.argv[2] if len(sys.argv) > 2 else "/private/tmp/floppy-scale/out"
metrics = sys.argv[3:] or ["cold_s", "warm_q", "bytes"]
data = {}
for f in glob.glob(f"{d}/surface_{label}_*.tsv"):
    size = re.search(rf"{label}_(\w+)\.tsv", f).group(1)
    for r in csv.DictReader(open(f), delimiter="\t"):
        data.setdefault(r["route"], {})[size] = r
sizes = ["0", "100", "1000", "10000", "100000", "250000", "shapes"]
for m in metrics:
    print(f"\n## {m}\n route | " + " | ".join(sizes))
    for route, by in sorted(data.items()):
        print(route, "|", " | ".join((by.get(s, {}).get(m) or "-") + ("!" if by.get(s, {}).get("status", "200") not in ("200",) else "") for s in sizes))
