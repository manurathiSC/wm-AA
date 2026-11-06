"""V5: the Step 1 rebuild reruns to the same g0_gate.csv after any change to shared data.

    python check_regression.py [--run headline]

Hashes data/parent_rebuild_hm/g0_gate.csv, reruns data/parent_rebuild_hm.py (which rewrites its own outputs from the raw files),
hashes again and writes evidence/<run>/v5_regression.json. Exits non-zero if the hash changed.
"""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
G = AA / "data" / "parent_rebuild_hm" / "g0_gate.csv"


def h(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


ap = argparse.ArgumentParser()
ap.add_argument("--run", default="headline")
a = ap.parse_args()
before = h(G)
r = subprocess.run([sys.executable, "data/parent_rebuild_hm.py"], cwd=AA, capture_output=True, text=True)
after = h(G)
res = {"g0_gate_sha256_before": before, "g0_gate_sha256_after": after, "identical": before == after, "returncode": r.returncode}
(HERE / "evidence" / a.run / "v5_regression.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(res)
sys.exit(0 if (before == after and r.returncode == 0) else 1)
