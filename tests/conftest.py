import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Never let tests hit real Gmail OAuth / send real mail, regardless of local .env.
os.environ["GMAIL_MCP_ENABLED"] = "false"
os.environ["SEND_ACTUAL_EMAILS"] = "false"

import pytest

from routers import jobs as jobs_module


@pytest.fixture(autouse=True)
def _clean_job_registries():
    """routers/jobs.py keeps job state in module-level dicts; isolate tests from each other."""
    jobs_module.job_states.clear()
    jobs_module.job_statuses.clear()
    yield
    jobs_module.job_states.clear()
    jobs_module.job_statuses.clear()
