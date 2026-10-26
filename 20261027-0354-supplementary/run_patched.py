"""Supplementary #306 run: page_checks.py with one db_facts query made to return NULL
instead of no row (candidate_count_latest when no candidate_score_v2 run exists).
The repo files are not changed; this wrapper lives outside the worktree."""
import importlib.util, json, sys
from pathlib import Path

WT = Path(sys.argv[1]); sys.argv = [str(WT / "tools/verify/page_checks.py")] + sys.argv[2:]
spec = importlib.util.spec_from_file_location("page_checks", WT / "tools/verify/page_checks.py")
pc = importlib.util.module_from_spec(spec); sys.modules["page_checks"] = pc
spec.loader.exec_module(pc)
table, sql = pc.db_facts.QUERIES["candidate_count_latest"]
pc.db_facts.QUERIES["candidate_count_latest"] = (table, f"SELECT ({sql})")
print("patched candidate_count_latest:", pc.db_facts.QUERIES["candidate_count_latest"][1], file=sys.stderr)
sys.exit(pc.main())
