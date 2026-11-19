"""Verify completed original suites, all fresh turns and the source snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from check_fresh import review
from check_repair import check


def verify(directory):
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf8"))
    changed = [name for name, digest in manifest["source_sha256"].items()
               if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest]
    gates = {"original": manifest.get("business_gate") == "passed",
             "same_source": not changed, "repair_invariants": check(directory)}
    for batch, count in (("A", 6), ("B", 4), ("C-unseen", 4)):
        path = directory / f"fresh-{batch}.json"
        rows = json.loads(path.read_text(encoding="utf8"))
        gates[batch] = (len(rows) == count and len({r["case"] for r in rows}) == count
                        and all(r["passed"] for r in rows) and review(path))
    result = {"passed": all(gates.values()), "gates": gates, "changed_files": changed}
    (directory / "release.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(result, ensure_ascii=False))
    return result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    sys.exit(not verify(parser.parse_args().directory))
