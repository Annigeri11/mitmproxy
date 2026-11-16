#!/usr/bin/env python3
"""Run each source file's test file in isolation and require 100% coverage of that file."""
from __future__ import annotations

import configparser
import contextlib
import io
import itertools
import multiprocessing
import sys
from pathlib import Path

import pytest

EXCLUDED_DIRS = (
    "mitmproxy/contrib/",
    "mitmproxy/test/",
    "mitmproxy/tools/",
    "mitmproxy/platform/",
)


def run_tests(src: str, test: str, fail: bool) -> None:
    stderr = io.StringIO()
    stdout = io.StringIO()
    module = Path(src).with_suffix("").as_posix().replace("/", ".")

    with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
        e = pytest.main(
            [
                "-qq",
                "--disable-pytest-warnings",
                "--cov",
                module,
                "--cov-fail-under",
                "100",
                "--cov-report",
                "term-missing:skip-covered",
                "-o",
                "faulthandler_timeout=0",
                test,
            ]
        )

    if e == 0:
        if fail:
            print(
                "FAIL DUE TO UNEXPECTED SUCCESS:",
                src,
                "Please remove this file from the individual_coverage exclude list.",
            )
            e = 42
        else:
            print(".")
    elif fail:
        print("Ignoring allowed fail:", src)
        e = 0
    else:
        out = stdout.getvalue()
        cov = [
            line
            for line in out.split("\n")
            if (src in line) or ("was never imported" in line)
        ]
        if len(cov) == 1:
            print("FAIL:", cov[0])
        else:
            print("FAIL:", src, test)
            print(stderr.getvalue())
            print(out)

    sys.exit(e)


def start_pytest(src: str, test: str, fail: bool) -> tuple[str, str, int | None]:
    # Run pytest in a new process, otherwise imports and modules might conflict.
    proc = multiprocessing.Process(target=run_tests, args=(src, test, fail))
    proc.start()
    proc.join()
    return src, test, proc.exitcode


def load_excludes() -> set[str]:
    """Read the exclude list from pyproject.toml, falling back to setup.cfg."""
    pyproject = Path("pyproject.toml")
    if pyproject.is_file():
        import tomllib  # Python 3.11+

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        exclude = data.get("tool", {}).get("individual_coverage", {}).get("exclude")
        if exclude is not None:
            return {str(f).strip() for f in exclude}

    c = configparser.ConfigParser()
    c.read("setup.cfg")
    raw = c.get("tool:individual_coverage", "exclude", fallback="")
    return {line.strip() for line in raw.splitlines() if line.strip()}


def main() -> None:
    no_individual_cov = load_excludes()

    src_files = [
        p.as_posix()
        for p in Path("mitmproxy").rglob("*.py")
        if p.name != "__init__.py"
        and not any(d in p.as_posix() for d in EXCLUDED_DIRS)
    ]
    if len(sys.argv) > 1:
        src_files = [f for f in src_files if sys.argv[1] in f]

    jobs = []
    for src in sorted(src_files):
        p = Path(src)
        test = Path("test") / p.parent / f"test_{p.name}"
        if test.is_file():
            jobs.append((src, test.as_posix(), src in no_individual_cov))

    results = list(itertools.starmap(start_pytest, jobs))

    if any(code != 0 for _, _, code in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
