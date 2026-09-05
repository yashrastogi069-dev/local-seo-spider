"""Automated contamination regression test suite.

Verifies:
1. No benchmark case IDs (DEV-, CAL-, BLIND-, ADV-, REG-) exist as string literals in production code (`app/`).
2. No benchmark queries exist as hardcoded strings in production code.
3. No benchmark target answers exist as hardcoded strings in production code.
"""

from __future__ import annotations

import pathlib
import pytest

from tests.fixtures.benchmark_cases import BENCHMARK_CASES

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"


def test_no_benchmark_case_ids_in_production_code() -> None:
    app_files = [f for f in APP_DIR.glob("**/*.py") if f.name != "evaluation.py"]
    assert len(app_files) > 10

    for af in app_files:
        text = af.read_text(encoding="utf-8")
        for case in BENCHMARK_CASES:
            cid = case["id"]
            assert cid not in text, f"Benchmark case ID {cid} found in production file {af.name}"


def test_no_benchmark_queries_in_production_code() -> None:
    app_files = [f for f in APP_DIR.glob("**/*.py") if f.name != "evaluation.py"]

    for af in app_files:
        text = af.read_text(encoding="utf-8")
        for case in BENCHMARK_CASES:
            q = case["query"]
            if len(q) > 12:
                assert q not in text, f"Benchmark query '{q}' found hardcoded in production file {af.name}"


def test_no_benchmark_target_facts_hardcoded_in_production_code() -> None:
    app_files = [f for f in APP_DIR.glob("**/*.py") if f.name != "evaluation.py"]

    for af in app_files:
        text = af.read_text(encoding="utf-8")
        for case in BENCHMARK_CASES:
            fact = case.get("target_fact", "").strip()
            # Only test non-trivial multi-word factual statements (> 15 chars)
            if len(fact) > 15:
                assert fact not in text, f"Benchmark target fact '{fact}' found hardcoded in production file {af.name}"
