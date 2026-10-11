"""Arms the network guard in child processes of ``python -m tools.test_db.netguard`` (see netguard.py).

Python imports ``sitecustomize`` at startup from the first ``PYTHONPATH`` entry that has one. Without the log
variable this file does nothing, so merely having the directory on a path never changes a process.
"""

import importlib.util
import os

_log = os.environ.get("TESTDB_NETGUARD_LOG")
if _log:
    _spec = importlib.util.spec_from_file_location(
        "_testdb_netguard", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "netguard.py")
    )
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    _module.install(_log)
