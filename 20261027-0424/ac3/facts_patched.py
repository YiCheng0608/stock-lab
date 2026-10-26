"""db_facts.py with candidate_count_latest wrapped in SELECT (...) (#307), as #306's run_patched.py."""
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("db_facts", Path(sys.argv[1]))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
t, s = m.QUERIES["candidate_count_latest"]; m.QUERIES["candidate_count_latest"] = (t, f"SELECT ({s})")
print(json.dumps(m.facts(Path(sys.argv[2])), ensure_ascii=False, indent=2, default=str))
