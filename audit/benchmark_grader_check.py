"""Challenge the assessment with corrupted copies of previously observed good fields."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from benchmark_score import attached, contract, read


def run(d):
    checks={}
    original=read(d/"family.json")
    bad=deepcopy(original)
    bad["after"]["facts"][0]["object"]="错误姓名"
    checks["stored_mismatch"]=contract("family",original)["stored_facts"] and not contract("family",bad)["stored_facts"]
    observed=read(d/"score.json")
    answer=observed["generation"]["payload"]
    docs={r["id"]:r for r in observed["retrieval"]["payload"]}
    citation=answer["citations"][0]
    valid=attached(citation,docs,answer["answer"])
    checks["wrong_source_locator"]=valid and not attached({**citation,"locator":"unrelated"},docs,answer["answer"])
    checks["quote_reassigned_to_another_document"]=valid and not attached({**citation,"id":"register"},docs,answer["answer"])
    original=read(d/"adopt.json")
    bad=deepcopy(original)
    bad["after"]["days"]=deepcopy(bad["before"]["days"])
    checks["claimed_adoption_without_commit"]=contract("adopt",original)["exact_commit"] and not contract("adopt",bad)["exact_commit"]
    (d/"grader-controls.json").write_text(json.dumps(checks,indent=2),encoding="utf8")
    return all(checks.values())


if __name__=="__main__":
    sys.exit(not run(Path(sys.argv[1])))
