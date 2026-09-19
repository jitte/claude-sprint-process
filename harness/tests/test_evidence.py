"""Tests for the harness's evidence contract: the readers (results.sh green/fresh,
record-test-fails.sh, tdd-audit.sh) and the writers (each adapter's convert-evidence
script).

Readers get their fixtures by writing evidence JSON files directly under the
fixture's evidence dir. Writers (convert-evidence) get their fixtures by writing
runner-specific raw output under SPRINT_RAW_DIR and reading back the evidence JSON
they print to stdout. Every fixture is confined to a throwaway temp directory via
CLAUDE_PROJECT_DIR.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from collections import namedtuple

# harness/tests/test_evidence.py -> harness/tests -> harness
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
HARNESS_DIR = os.path.dirname(THIS_DIR)

# Evidence directory used by the fixtures (matches evidence.dir in sprint.config.json).
EVIDENCE_DIR = ".sprint/test-result"


def now_epoch():
    return int(time.time())


def write_file(root, rel_path, content):
    file_path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        f.write(content)
    return file_path


def base_config(root):
    """The fixture config shape shared by every case in this file."""
    return {
        "schemaVersion": 1,
        "project": {"name": "fixture", "timezone": "Asia/Tokyo"},
        "docs": {
            "templates": os.path.join(root, "tpl"),
            "livingDirs": ["docs/05_specifications"],
            "sprintRoot": "docs/07_plans",
            "specDir": "spec",
        },
        "tasks": ["lint", "typecheck", "build", "test", "e2e"],
        "components": {
            "app": {
                "dir": "app",
                "role": "backend",
                "src": ["app/src/**"],
                "tests": ["app/src/**/*.test.ts"],
                "adapters": {"lint": "fake", "test": "fake"},
            },
            "ui": {
                "dir": "ui",
                "role": "frontend",
                "src": ["ui/src/**"],
                "tests": ["ui/src/**/*.test.tsx", "ui/e2e/**/*.spec.ts"],
                "adapters": {"test": "fake"},
            },
        },
        "evidence": {"dir": EVIDENCE_DIR},
        "sets": {},
        "gateToolsDirs": [os.path.join(root, "gate-tools")],
        "gates": {"code": {}, "docs": {}},
    }


def write_config(root, config):
    write_file(root, "sprint.config.json", json.dumps(config, indent=2) + "\n")


def fixture_env(root, extra=None):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = root
    for key in (
        "SPRINT_CONFIG",
        "SPRINT_TZ",
        "SPRINT_GATE",
        "SPRINT_ADAPTERS_DIR",
        "TDD_TEST_MD",
        "TDD_RESULTS_DIR",
        "GATE_ALLOW_WARN",
    ):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def mk_evidence(component, task, over=None):
    """An evidence JSON object (schemaVersion 1). Defaults to a passing run;
    top-level fields in `over` replace the defaults wholesale (no deep merge),
    same as the evidence contract's writers produce them."""
    over = over or {}
    now = now_epoch()
    ev = {
        "schemaVersion": 1,
        "component": component,
        "task": task,
        "adapter": "fake",
        "status": "pass",
        "counts": {"passed": 1, "failed": 0, "skipped": 0},
        "errors": 0,
        "warnings": 0,
        "tests": [],
        "started_at": now - 10,
        "finished_at": now,
    }
    ev.update(over)
    return ev


def write_evidence(root, ev, suffix=""):
    write_file(
        root,
        f"{EVIDENCE_DIR}/{ev['component']}.{ev['task']}{suffix}.json",
        json.dumps(ev, indent=2) + "\n",
    )


def run_results(root, args, extra_env=None):
    return subprocess.run(
        ["bash", os.path.join(HARNESS_DIR, "gate-tools", "results.sh"), *args],
        cwd=root,
        env=fixture_env(root, extra_env),
        capture_output=True,
        text=True,
    )


def write_green_set(root, overrides=None):
    """Re-write the three entries results.sh reads (app.lint / app.test / ui.test)
    in a fully green state, then layer any per-entry overrides on top."""
    overrides = overrides or {}
    shutil.rmtree(os.path.join(root, EVIDENCE_DIR), ignore_errors=True)

    lint_over = {"counts": {"passed": 0, "failed": 0, "skipped": 0}}
    lint_over.update(overrides.get("app.lint", {}))
    write_evidence(root, mk_evidence("app", "lint", lint_over))
    write_evidence(root, mk_evidence("app", "test", overrides.get("app.test", {})))
    write_evidence(root, mk_evidence("ui", "test", overrides.get("ui.test", {})))


def test_md_lines(with_format_row):
    """A minimal TEST.md with two well-formed test-definition rows, plus
    optionally a third row that omits its test-file column."""
    rows = [
        "# TEST — fixture",
        "",
        "## Test specification",
        "",
        "| Test ID | Spec ref | Test file | Description |",
        "|---------|----------|-----------|--------------|",
        "| TEST-1-1-1.1 | N-1.1 | app/src/a.test.ts | first |",
        "| TEST-1-1-1.2 | N-1.2 | app/src/b.test.ts | second |",
    ]
    if with_format_row:
        rows.append("| TEST-1-1-1.3 | N-1.3 | — | no file column |")
    rows.append("")
    return "\n".join(rows)


def run_tdd_audit(root, test_md):
    return subprocess.run(
        ["bash", os.path.join(HARNESS_DIR, "gate-tools", "tdd-audit.sh")],
        cwd=root,
        env=fixture_env(root, {"TDD_TEST_MD": test_md}),
        capture_output=True,
        text=True,
    )


ConvertResult = namedtuple("ConvertResult", ["rc", "out", "evidence"])


def convert_evidence(root, adapter, verb, component=None, component_dir=None):
    """Run one adapter's convert-evidence script and parse the evidence JSON it
    prints to stdout."""
    component = component or "app"
    component_dir = component_dir or os.path.join(root, "app")
    os.makedirs(component_dir, exist_ok=True)
    raw_dir = os.path.join(root, EVIDENCE_DIR, "raw", f"{component}.{verb}")
    result = subprocess.run(
        ["bash", os.path.join(HARNESS_DIR, "adapters", adapter, "convert-evidence"), verb],
        cwd=component_dir,
        env=fixture_env(
            root,
            {
                "SPRINT_ROOT": root,
                "SPRINT_COMPONENT": component,
                "SPRINT_COMPONENT_DIR": component_dir,
                "SPRINT_TASK": verb,
                "SPRINT_RAW_DIR": raw_dir,
            },
        ),
        capture_output=True,
        text=True,
    )
    out = result.stdout or ""
    try:
        evidence = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        evidence = {}
    return ConvertResult(result.returncode, out, evidence)


def write_raw(root, component, verb, name, content):
    write_file(root, f"{EVIDENCE_DIR}/raw/{component}.{verb}/{name}", content)


class HarnessEvidenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp_dirs = []

    def tearDown(self):
        for d in self._tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._tmp_dirs = []

    def mk_root(self):
        d = os.path.realpath(tempfile.mkdtemp(prefix="csp-harness-evidence-"))
        self._tmp_dirs.append(d)
        return d

    # -- gate-tools/results.sh ------------------------------------------------

    def test_green_judges_from_evidence_json_only(self):
        root = self.mk_root()
        write_config(root, base_config(root))

        # everything passes
        write_green_set(root)
        self.assertEqual(run_results(root, ["green"]).returncode, 0)

        # lint errors are an implementation failure (2)
        write_green_set(root, {"app.lint": {"status": "fail", "errors": 2}})
        lint_err = run_results(root, ["green"])
        self.assertEqual(lint_err.returncode, 2)
        self.assertIn("app.lint: 2 errors", lint_err.stdout + lint_err.stderr)

        # warnings fail by default; GATE_ALLOW_WARN=1 ignores them
        write_green_set(root, {"app.lint": {"warnings": 3}})
        warn = run_results(root, ["green"])
        self.assertEqual(warn.returncode, 2)
        self.assertIn("app.lint: 3 warnings", warn.stdout + warn.stderr)
        self.assertEqual(
            run_results(root, ["green"], {"GATE_ALLOW_WARN": "1"}).returncode, 0
        )

        # test failures/skips are a test problem (3)
        write_green_set(
            root,
            {"app.test": {"status": "fail", "counts": {"passed": 0, "failed": 1, "skipped": 0}}},
        )
        failed = run_results(root, ["green"])
        self.assertEqual(failed.returncode, 3)
        self.assertIn("app.test: 1 failed", failed.stdout + failed.stderr)

        write_green_set(
            root, {"app.test": {"counts": {"passed": 1, "failed": 0, "skipped": 2}}}
        )
        skipped = run_results(root, ["green"])
        self.assertEqual(skipped.returncode, 3)
        self.assertIn("app.test: 2 skipped", skipped.stdout + skipped.stderr)

        # a missing evidence file is an infrastructure problem (4)
        write_green_set(root)
        os.remove(os.path.join(root, EVIDENCE_DIR, "ui.test.json"))
        missing = run_results(root, ["green"])
        self.assertEqual(missing.returncode, 4)
        self.assertIn("ui.test.json not found", missing.stdout + missing.stderr)

        # .partial.json files are never read
        write_green_set(root)
        write_evidence(
            root,
            mk_evidence("app", "test", {"status": "fail", "counts": {"passed": 0, "failed": 5, "skipped": 0}}),
            ".partial",
        )
        self.assertEqual(run_results(root, ["green"]).returncode, 0)

    def test_fresh_judges_by_finished_at_against_source_globs(self):
        root = self.mk_root()
        write_config(root, base_config(root))

        now = now_epoch()
        write_green_set(
            root,
            {
                "app.lint": {"finished_at": now - 50},
                "app.test": {"finished_at": now - 50},
                "ui.test": {"finished_at": now - 50},
            },
        )

        src_a = write_file(root, "app/src/a.ts", "export const a = 1\n")
        src_b = write_file(root, "ui/src/b.tsx", "export const B = 1\n")
        other = write_file(root, "other/c.ts", "export const c = 1\n")
        for f in (src_a, src_b, other):
            os.utime(f, (now - 100, now - 100))

        self.assertEqual(run_results(root, ["fresh"]).returncode, 0)

        # touching ui's source makes ui.test's evidence stale
        os.utime(src_b, (now + 10, now + 10))
        stale = run_results(root, ["fresh"])
        self.assertEqual(stale.returncode, 4)
        self.assertIn("ui.test is stale", stale.stdout + stale.stderr)

        # a file matching no glob doesn't affect freshness
        os.utime(src_b, (now - 100, now - 100))
        os.utime(other, (now + 10, now + 10))
        self.assertEqual(run_results(root, ["fresh"]).returncode, 0)

    # -- hooks/record-test-fails.sh -------------------------------------------

    def test_record_test_fails_writes_per_task_counts(self):
        root = self.mk_root()
        write_config(root, base_config(root))
        write_file(root, ".sprint/flags.json", json.dumps({"active": ""}) + "\n")

        write_evidence(
            root,
            mk_evidence("app", "lint", {"status": "fail", "errors": 2, "counts": {"passed": 0, "failed": 0, "skipped": 0}}),
        )
        write_evidence(
            root, mk_evidence("app", "test", {"status": "fail", "counts": {"passed": 1, "failed": 3, "skipped": 0}})
        )
        write_evidence(root, mk_evidence("ui", "test", {"counts": {"passed": 2, "failed": 0, "skipped": 0}}))

        result = subprocess.run(
            ["bash", os.path.join(HARNESS_DIR, "hooks", "record-test-fails.sh")],
            cwd=root,
            env=fixture_env(root),
            input=json.dumps({"tool_input": {"command": "bash harness/bin/sprint run test"}}),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '{"continue":true}')

        with open(os.path.join(root, ".sprint", "test-fails.json")) as f:
            written = json.load(f)
        self.assertIsNotNone(written.get("recorded_at"))
        del written["recorded_at"]
        self.assertEqual(written, {"total": 5, "tasks": {"app.lint": 2, "app.test": 3, "ui.test": 0}})

    # -- gate-tools/tdd-audit.sh ------------------------------------------------

    def test_tdd_audit_matches_test_ids_against_evidence_tests(self):
        root = self.mk_root()
        write_config(root, base_config(root))
        test_md = write_file(root, "docs/07_plans/w/s/TEST.md", test_md_lines(True))
        write_file(
            root,
            ".sprint/flags.json",
            json.dumps({"active": "1-1", "sprints": {"1-1": {"sprint_dir": "docs/07_plans/w/s", "kind": "code", "stage": "DOCS"}}}) + "\n",
        )

        tests = [
            {"file": "src/a.test.ts", "name": "TEST-1-1-1.1 x", "status": "passed"},
            {"file": "src/b.test.ts", "name": "TEST-1-1-1.2 y", "status": "skipped"},
        ]
        write_evidence(
            root, mk_evidence("app", "test", {"status": "pass", "counts": {"passed": 1, "failed": 0, "skipped": 1}, "tests": tests})
        )

        # FORMAT (1 = spec problem) is the most upstream. NOT-PASS is reported alongside it.
        both = run_tdd_audit(root, test_md)
        both_out = both.stdout + both.stderr
        self.assertRegex(both_out, r"NOT-PASS\s+TEST-1-1-1\.2")
        self.assertRegex(both_out, r"FORMAT\s+TEST-1-1-1\.3")
        self.assertEqual(both.returncode, 1)

        # removing the FORMAT row leaves only NOT-PASS (3 = test problem)
        with open(test_md, "w") as f:
            f.write(test_md_lines(False))
        self.assertEqual(run_tdd_audit(root, test_md).returncode, 3)

        # .partial.json is never read (still NOT-PASS even though it "passes" there)
        write_evidence(
            root,
            mk_evidence("app", "test", {"tests": [{"file": "src/b.test.ts", "name": "TEST-1-1-1.2 y", "status": "passed"}]}),
            ".partial",
        )
        self.assertEqual(run_tdd_audit(root, test_md).returncode, 3)

        # no evidence at all -> 4 (infrastructure problem)
        shutil.rmtree(os.path.join(root, EVIDENCE_DIR), ignore_errors=True)
        self.assertEqual(run_tdd_audit(root, test_md).returncode, 4)

    # -- adapters/*/convert-evidence --------------------------------------------

    def test_node_vitest_adapter_converts_jest_style_json(self):
        root = self.mk_root()
        write_config(root, base_config(root))
        component_dir = os.path.join(root, "app")
        os.makedirs(os.path.join(component_dir, "src"), exist_ok=True)

        vitest_json = {
            "numTotalTestSuites": 2,
            "numTotalTests": 5,
            "success": False,
            "testResults": [
                {
                    "name": os.path.join(component_dir, "src", "a.test.ts"),
                    "status": "failed",
                    "assertionResults": [
                        {"ancestorTitles": ["A"], "title": "one", "fullName": "A one", "status": "passed"},
                        {"ancestorTitles": ["A"], "title": "two", "fullName": "A two", "status": "passed"},
                        {"ancestorTitles": ["A"], "title": "three", "fullName": "A three", "status": "failed"},
                    ],
                },
                {
                    "name": os.path.join(component_dir, "src", "b.test.ts"),
                    "status": "passed",
                    "assertionResults": [
                        {"ancestorTitles": ["B"], "title": "four", "fullName": "B four", "status": "pending"},
                        {"ancestorTitles": ["B"], "title": "five", "fullName": "B five", "status": "todo"},
                    ],
                },
            ],
        }
        write_raw(root, "app", "test", "result.json", json.dumps(vitest_json, indent=2) + "\n")
        write_raw(root, "app", "test", "stdout.txt", "Test Files  1 failed | 1 passed\n")

        result = convert_evidence(root, "node-vitest", "test")
        evidence = result.evidence

        self.assertEqual(evidence["counts"], {"passed": 2, "failed": 1, "skipped": 1})
        self.assertEqual(evidence["status"], "fail")
        self.assertEqual(len(evidence["tests"]), 5)
        self.assertEqual(
            [t["file"] for t in evidence["tests"]],
            ["src/a.test.ts", "src/a.test.ts", "src/a.test.ts", "src/b.test.ts", "src/b.test.ts"],
        )
        self.assertEqual(
            [t["status"] for t in evidence["tests"]],
            ["passed", "passed", "failed", "skipped", "todo"],
        )
        self.assertIn("A one", [t["name"] for t in evidence["tests"]])

    def test_eslint_tsc_adapter_lint_sums_summary_counts(self):
        root = self.mk_root()
        write_config(root, base_config(root))

        write_raw(
            root,
            "app",
            "lint",
            "stdout.txt",
            "\n".join(
                [
                    "/x/a.ts",
                    "  1:1  error  something  rule/a",
                    "",
                    "✖ 5 problems (2 errors, 3 warnings)",
                    "",
                    "/x/b.ts",
                    "  2:1  error  other  rule/b",
                    "",
                    "✖ 1 problem (1 error, 0 warnings)",
                    "",
                ]
            ),
        )

        failing = convert_evidence(root, "eslint-tsc", "lint")
        self.assertEqual(failing.evidence["errors"], 3)
        self.assertEqual(failing.evidence["warnings"], 3)
        self.assertEqual(failing.evidence["status"], "fail")

        write_raw(root, "app", "lint", "stdout.txt", "")
        clean = convert_evidence(root, "eslint-tsc", "lint")
        self.assertEqual(clean.evidence["errors"], 0)
        self.assertEqual(clean.evidence["warnings"], 0)
        self.assertEqual(clean.evidence["status"], "pass")

    def test_eslint_tsc_adapter_typecheck_counts_error_ts_lines(self):
        root = self.mk_root()
        write_config(root, base_config(root))

        write_raw(
            root,
            "app",
            "typecheck",
            "stdout.txt",
            "\n".join(
                [
                    "src/a.ts(1,1): error TS2322: Type 'string' is not assignable to type 'number'.",
                    "src/b.ts(2,3): error TS2322: Type 'number' is not assignable to type 'string'.",
                    "",
                ]
            ),
        )

        failing = convert_evidence(root, "eslint-tsc", "typecheck")
        self.assertEqual(failing.evidence["errors"], 2)
        self.assertEqual(failing.evidence["status"], "fail")

        write_raw(root, "app", "typecheck", "stdout.txt", "")
        clean = convert_evidence(root, "eslint-tsc", "typecheck")
        self.assertEqual(clean.evidence["errors"], 0)
        self.assertEqual(clean.evidence["status"], "pass")

    def test_vite_build_adapter_checks_success_marker(self):
        root = self.mk_root()
        write_config(root, base_config(root))

        write_raw(
            root,
            "ui",
            "build",
            "stdout.txt",
            "\n".join(["vite v5.0.0 building for production...", "✓ 100 modules transformed.", "✓ built in 3.2s", ""]),
        )
        ok = convert_evidence(root, "vite-build", "build", component="ui", component_dir=os.path.join(root, "ui"))
        self.assertEqual(ok.evidence["status"], "pass")

        write_raw(
            root,
            "ui",
            "build",
            "stdout.txt",
            "\n".join(["vite v5.0.0 building for production...", "error during build", ""]),
        )
        ng = convert_evidence(root, "vite-build", "build", component="ui", component_dir=os.path.join(root, "ui"))
        self.assertEqual(ng.evidence["status"], "fail")

    def test_playwright_adapter_aggregates_results_by_spec(self):
        root = self.mk_root()
        write_config(root, base_config(root))
        component_dir = os.path.join(root, "ui")
        os.makedirs(os.path.join(component_dir, "e2e"), exist_ok=True)

        def make_spec(title, line, status, results):
            return {
                "title": title,
                "ok": status in ("expected", "skipped"),
                "tags": [],
                "file": "e2e/a.spec.ts",
                "line": line,
                "column": 1,
                "tests": [
                    {
                        "timeout": 30000,
                        "expectedStatus": "skipped" if status == "skipped" else "passed",
                        "projectName": "chromium",
                        "status": status,
                        "results": results,
                    }
                ],
            }

        playwright_json = {
            "config": {"rootDir": component_dir},
            "suites": [
                {
                    "title": "e2e/a.spec.ts",
                    "file": "e2e/a.spec.ts",
                    "specs": [
                        make_spec("all expected", 3, "expected", [{"status": "passed", "retry": 0}]),
                        make_spec("has unexpected", 8, "unexpected", [{"status": "failed", "retry": 0}]),
                        make_spec(
                            "has flaky",
                            13,
                            "flaky",
                            [{"status": "failed", "retry": 0}, {"status": "passed", "retry": 1}],
                        ),
                        make_spec("has skipped", 18, "skipped", [{"status": "skipped", "retry": 0}]),
                    ],
                    "suites": [],
                }
            ],
            "errors": [],
        }
        write_raw(root, "ui", "test", "result.json", json.dumps(playwright_json, indent=2) + "\n")
        write_raw(root, "ui", "test", "stdout.txt", "4 tests\n")

        result = convert_evidence(root, "playwright", "test", component="ui", component_dir=component_dir)
        evidence = result.evidence

        self.assertEqual(len(evidence["tests"]), 4)
        self.assertEqual([t["status"] for t in evidence["tests"]], ["passed", "failed", "flaky", "skipped"])
        # flaky is counted separately in counts.flaky (the evidence contract tracks the 3 base statuses individually)
        self.assertEqual(evidence["counts"]["passed"], 1)
        self.assertEqual(evidence["counts"]["failed"], 1)
        self.assertEqual(evidence["counts"]["skipped"], 1)
        self.assertEqual(evidence["status"], "fail")


if __name__ == "__main__":
    unittest.main()
