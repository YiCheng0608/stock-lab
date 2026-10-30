"""Throwaway mutation of #378 (never merged): a test that runs only where GITHUB_ACTIONS is unset."""

import os

import pytest


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason="skipped on the runner; the docker job's container has no GITHUB_ACTIONS",
)
def test_mutation_runs_only_in_the_image():
    assert True
