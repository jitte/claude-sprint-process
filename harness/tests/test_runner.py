#!/usr/bin/env python3
"""Tests for harness/bin/sprint, harness/tools/gate-check.sh, harness/gate-tools/*
and harness/tools/spec-graph.sh, exercised as black-box subprocesses.

Python 3 standard library only (unittest / tempfile / subprocess / json). No
node/bun/vitest dependency — just python3, bash, jq and git on PATH.

Fixtures are synthetic: each test builds its own temporary project root with a
minimal sprint.config.json (and, where needed, fake adapters / gate tools /
templates) rather than depending on any real project checked out on disk.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# Repository root: this file lives at <repo>/harness/tests/test_runner.py.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HARNESS = os.path.join(REPO_ROOT, "harness")
SPRINT_BIN = os.path.join(HARNESS, "bin", "sprint")

# Evidence directory used by the fixture config (sprint.config.json evidence.dir).
EVIDENCE_DIR = ".sprint/test-result"

# Some gate-tools shell out to GNU-only tool behavior: `xargs -d '\n'` (a GNU
# extension; BSD xargs errors out, which the scripts' own `2>/dev/null`
# swallows, silently producing empty results) and `wc -w` on stdin (BSD wc
# right-pads its count to a fixed width; GNU wc does not, and the scripts
# splice the count directly into a message). If GNU findutils/coreutils are
# installed alongside the system tools (common on macOS via Homebrew), prefer
# them so the scripts behave as they do on Linux; otherwise leave PATH
# untouched (the scripts, not this test file, would need updating for a
# GNU-less environment).
_GNUBIN_CANDIDATES = [
    "/opt/homebrew/opt/findutils/libexec/gnubin",
    "/usr/local/opt/findutils/libexec/gnubin",
    "/opt/homebrew/opt/coreutils/libexec/gnubin",
    "/usr/local/opt/coreutils/libexec/gnubin",
]
_GNUBIN_DIRS = [p for p in _GNUBIN_CANDIDATES if os.path.isdir(p)]


def _grep_supports_dash_p():
    try:
        p = subprocess.run(
            ["grep", "-oP", r"\d+"], input="a123b", capture_output=True, text=True
        )
        return p.returncode == 0 and p.stdout.strip() == "123"
    except OSError:
        return False


_PYTHON3_SHIM_DIR = None
_PYTHON3_SHIM_BUILT = False


def _python3_shim_dir():
    """Directory to prepend to PATH so a plain `python3` reliably resolves.

    spec-graph.sh execs a bare `python3` from PATH. On a machine using a
    version manager (asdf/pyenv) whose shim requires a `.tool-versions` file,
    invoking it from an arbitrary temp fixture directory (no such file
    anywhere above it) fails outright. Route `python3` to this same
    interpreter (sys.executable) instead, unconditionally — it's already
    known to work since it's the one running this test.
    """
    global _PYTHON3_SHIM_DIR, _PYTHON3_SHIM_BUILT
    if _PYTHON3_SHIM_BUILT:
        return _PYTHON3_SHIM_DIR
    _PYTHON3_SHIM_BUILT = True
    shim_dir = tempfile.mkdtemp(prefix="csp-python3-shim-")
    shim_path = os.path.join(shim_dir, "python3")
    with open(shim_path, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
    st = os.stat(shim_path)
    os.chmod(shim_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    _PYTHON3_SHIM_DIR = shim_dir
    return _PYTHON3_SHIM_DIR


_GREP_SHIM_DIR = None
_GREP_SHIM_BUILT = False


def _grep_shim_dir():
    """Directory to prepend to PATH so `grep -P`/`-oP`/`-qP` work.

    One gate-tool (tdd-exists.sh) relies on `grep -P` (a GNU extension for
    Perl-compatible regex, including `\\K` and lookaround). BSD grep (macOS's
    system grep) doesn't support -P at all. If the system grep already
    supports it (GNU grep, e.g. on Linux), this is a no-op. Otherwise, if
    `pcregrep` (PCRE-native, so `-P`-equivalent by default) happens to be
    available, build a tiny shim `grep` that routes any flag cluster
    containing `P` to pcregrep (with the `P` stripped) and everything else to
    the real grep — purely a local compatibility shim, not a repo file.
    """
    global _GREP_SHIM_DIR, _GREP_SHIM_BUILT
    if _GREP_SHIM_BUILT:
        return _GREP_SHIM_DIR
    _GREP_SHIM_BUILT = True
    if _grep_supports_dash_p():
        return _GREP_SHIM_DIR
    pcregrep = shutil.which("pcregrep")
    real_grep = shutil.which("grep")
    if not pcregrep or not real_grep:
        return _GREP_SHIM_DIR
    shim_dir = tempfile.mkdtemp(prefix="csp-grep-shim-")
    script = (
        "#!/bin/bash\n"
        "args=()\n"
        "routed=0\n"
        'for a in "$@"; do\n'
        "  case \"$a\" in\n"
        "    -*P*)\n"
        '      stripped="${a//P/}"\n'
        '      [ "$stripped" = "-" ] || args+=("$stripped")\n'
        "      routed=1\n"
        "      ;;\n"
        "    *)\n"
        '      args+=("$a")\n'
        "      ;;\n"
        "  esac\n"
        "done\n"
        'if [ "$routed" = "1" ]; then\n'
        f'  exec "{pcregrep}" "${{args[@]}}"\n'
        "fi\n"
        f'exec "{real_grep}" "${{args[@]}}"\n'
    )
    shim_path = os.path.join(shim_dir, "grep")
    with open(shim_path, "w", encoding="utf-8") as f:
        f.write(script)
    st = os.stat(shim_path)
    os.chmod(shim_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    _GREP_SHIM_DIR = shim_dir
    return _GREP_SHIM_DIR


def shell_env(base=None):
    """Build a subprocess environment for invoking the harness's shell tools.

    Forces the C locale: some of these scripts unbrace a `$var` right before a
    multi-byte (Japanese) literal (e.g. `$adapter（...）`), which a UTF-8
    locale's multibyte-aware identifier parsing in bash can misparse as part
    of the variable name. The scripts' own output text is unaffected — this
    only changes how bash tokenizes, not the literal bytes it prints.
    """
    env = dict(base) if base is not None else dict(os.environ)
    env["LC_ALL"] = "C"
    prefix_dirs = [d for d in (_python3_shim_dir(), *_GNUBIN_DIRS, _grep_shim_dir()) if d]
    if prefix_dirs:
        env["PATH"] = os.pathsep.join(prefix_dirs) + os.pathsep + env.get("PATH", "")
    return env


def write_file(root, rel_path, content):
    file_path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return file_path


def write_exec(root, rel_path, content):
    file_path = write_file(root, rel_path, content)
    st = os.stat(file_path)
    os.chmod(file_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return file_path


class HarnessTestCase(unittest.TestCase):
    """Shared temp-dir bookkeeping for harness subprocess tests."""

    def setUp(self):
        self.tmp_dirs = []

    def tearDown(self):
        for d in self.tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self.tmp_dirs = []

    def mk_root(self):
        d = tempfile.mkdtemp(prefix="csp-harness-runner-")
        d = os.path.realpath(d)
        self.tmp_dirs.append(d)
        return d


class RunnerFixtureMixin:
    """Fixture builders shared by the `sprint run` / gate-check / `sprint new` /
    set-contract tests (mirrors the fixture config used across those tests)."""

    def base_config(self, root):
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

    def write_config(self, root, config):
        write_file(root, "sprint.config.json", json.dumps(config, indent=2) + "\n")

    def fixture_env(self, root, extra=None):
        env = shell_env()
        env["CLAUDE_PROJECT_DIR"] = root
        env["SPRINT_ADAPTERS_DIR"] = os.path.join(root, "adapters")
        for key in (
            "SPRINT_CONFIG",
            "SPRINT_TZ",
            "SPRINT_GATE",
            "SPRINT_RUN_EXIT",
            "TDD_TEST_MD",
            "TDD_RESULTS_DIR",
            "API_ROUTES_ROOT",
            "API_ROUTES_IMPL_CMD",
            "ACCOUNTS_ROOT",
            "ACCOUNTS_IMPL_CMD",
            "SIZE_AUDIT_ROOT",
            "SPEC_GRAPH_ROOT",
        ):
            env.pop(key, None)
        if extra:
            env.update(extra)
        return env

    def write_fake_adapter(self, root):
        runner = "\n".join(
            [
                "#!/bin/bash",
                "# fake runner: prints a marker, exit code driven by env vars.",
                'echo "fake $SPRINT_COMPONENT $SPRINT_TASK"',
                'case "$SPRINT_TASK" in',
                '  lint) exit "${FAKE_EXIT_LINT:-${FAKE_EXIT:-0}}" ;;',
                '  *)    exit "${FAKE_EXIT:-0}" ;;',
                "esac",
                "",
            ]
        )
        write_exec(root, "adapters/fake/run-lint", runner)
        write_exec(root, "adapters/fake/run-test", runner)

        convert = "\n".join(
            [
                "#!/bin/bash",
                "# fake convert-evidence: writes the evidence-contract JSON to stdout.",
                'verb="${SPRINT_TASK:-$1}"',
                'failed="${FAKE_FAILED:-0}"',
                "status=pass",
                'if [ "${SPRINT_RUN_EXIT:-0}" != "0" ] || [ "$failed" != "0" ]; then status=fail; fi',
                'printf \'{"schemaVersion":1,"component":"%s","task":"%s","adapter":"fake","status":"%s",\' \\',
                '  "$SPRINT_COMPONENT" "$verb" "$status"',
                'printf \'"counts":{"passed":1,"failed":%s,"skipped":0},"errors":0,"warnings":0,\' "$failed"',
                'printf \'"tests":[{"file":"src/a.test.ts","name":"fake %s %s","status":"passed"}],\' \\',
                '  "$SPRINT_COMPONENT" "$verb"',
                'printf \'"started_at":1,"finished_at":2}\\n\'',
                "",
            ]
        )
        write_exec(root, "adapters/fake/convert-evidence", convert)

    def mk_runner_fixture(self, mutate=None):
        root = self.mk_root()
        config = self.base_config(root)
        if mutate:
            mutate(config)
        self.write_config(root, config)
        self.write_fake_adapter(root)
        write_file(root, ".sprint/flags.json", json.dumps({"active": ""}) + "\n")
        os.makedirs(os.path.join(root, "app", "src"), exist_ok=True)
        os.makedirs(os.path.join(root, "ui", "src"), exist_ok=True)
        return root

    def run_sprint(self, root, args, extra_env=None):
        return subprocess.run(
            ["bash", SPRINT_BIN, *args],
            cwd=root,
            env=self.fixture_env(root, extra_env),
            capture_output=True,
            text=True,
        )

    def evidence_path(self, root, name):
        return os.path.join(root, EVIDENCE_DIR, name)

    def read_evidence(self, root, name):
        with open(self.evidence_path(root, name), encoding="utf-8") as f:
            return json.load(f)


class SprintRunTaskContractTests(RunnerFixtureMixin, HarnessTestCase):
    """harness/bin/sprint run — task contract."""

    def test_run_processes_components_in_config_order_and_writes_pre_and_evidence(self):
        root = self.mk_runner_fixture(
            lambda c: c["components"]["app"].__setitem__(
                "pre", {"test": 'touch "$SPRINT_ROOT/pre-ran"'}
            )
        )

        result = self.run_sprint(root, ["run", "test"])
        self.assertEqual(result.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(root, "pre-ran")))

        app_test = self.read_evidence(root, "app.test.json")
        self.assertEqual(app_test["component"], "app")
        self.assertEqual(app_test["task"], "test")
        self.assertEqual([t["name"] for t in app_test["tests"]], ["fake app test"])

        ui_test = self.read_evidence(root, "ui.test.json")
        self.assertEqual(ui_test["component"], "ui")
        self.assertEqual(ui_test["task"], "test")

        with open(
            os.path.join(root, EVIDENCE_DIR, "raw", "app.test", "stdout.txt"),
            encoding="utf-8",
        ) as f:
            raw = f.read()
        self.assertIn("fake app test", raw)

        # Passing <component> restricts the run to just that component.
        only_ui = self.mk_runner_fixture()
        self.assertEqual(self.run_sprint(only_ui, ["run", "test", "ui"]).returncode, 0)
        self.assertTrue(os.path.exists(self.evidence_path(only_ui, "ui.test.json")))
        self.assertFalse(os.path.exists(self.evidence_path(only_ui, "app.test.json")))

        # A component without an adapter for the verb is skipped, not failed.
        lint_only = self.mk_runner_fixture()
        self.assertEqual(self.run_sprint(lint_only, ["run", "lint"]).returncode, 0)
        self.assertTrue(os.path.exists(self.evidence_path(lint_only, "app.lint.json")))
        self.assertFalse(os.path.exists(self.evidence_path(lint_only, "ui.lint.json")))

    def test_missing_adapter_is_reported_once_and_exits_4(self):
        root = self.mk_runner_fixture(
            lambda c: c["components"]["ui"].__setitem__("adapters", {"test": "nope"})
        )

        result = self.run_sprint(root, ["run", "test"])
        out = result.stdout + result.stderr

        self.assertEqual(result.returncode, 4)
        hits = [
            line for line in out.split("\n") if "アダプタが無い: nope（ui.test）" in line
        ]
        self.assertEqual(len(hits), 1)
        # app was already processed before ui failed.
        self.assertTrue(os.path.exists(self.evidence_path(root, "app.test.json")))

    def test_pre_failure_partial_run_and_runner_failure_exit_codes(self):
        # A non-zero pre stops the run immediately with exit 4.
        pre_fail = self.mk_runner_fixture(
            lambda c: c["components"]["app"].__setitem__("pre", {"test": "false"})
        )
        pre_result = self.run_sprint(pre_fail, ["run", "test"])
        self.assertEqual(pre_result.returncode, 4)
        self.assertIn(
            "app.test: pre が失敗（exit 1）", pre_result.stdout + pre_result.stderr
        )

        # Extra args after `--` make it a partial run; evidence goes to *.partial.json.
        partial = self.mk_runner_fixture()
        partial_result = self.run_sprint(partial, ["run", "test", "app", "--", "foo"])
        self.assertEqual(partial_result.returncode, 0)
        self.assertTrue(os.path.exists(self.evidence_path(partial, "app.test.partial.json")))
        self.assertFalse(os.path.exists(self.evidence_path(partial, "app.test.json")))

        # A non-zero runner still lets the remaining components run, then exits 2.
        failing = self.mk_runner_fixture()
        fail_result = self.run_sprint(failing, ["run", "test"], {"FAKE_EXIT": "1"})
        self.assertEqual(fail_result.returncode, 2)
        self.assertTrue(os.path.exists(self.evidence_path(failing, "app.test.json")))
        self.assertTrue(os.path.exists(self.evidence_path(failing, "ui.test.json")))

        # `run all` fail-fasts per verb: a lint failure stops before test runs.
        all_run = self.mk_runner_fixture()
        all_result = self.run_sprint(all_run, ["run", "all"], {"FAKE_EXIT_LINT": "1"})
        self.assertEqual(all_result.returncode, 2)
        self.assertTrue(os.path.exists(self.evidence_path(all_run, "app.lint.json")))
        self.assertFalse(os.path.exists(self.evidence_path(all_run, "app.test.json")))


class GateCheckDefinitionTests(RunnerFixtureMixin, HarnessTestCase):
    """harness/tools/gate-check.sh — gate definitions."""

    def test_gate_check_reads_gates_and_gate_tools_dirs_from_config(self):
        root = self.mk_root()
        config = self.base_config(root)
        config["gateToolsDirs"] = [os.path.join(root, "tools-a"), os.path.join(root, "tools-b")]
        config["gates"] = {"code": {"TEST": ["fake-pass", "fake-fail"]}, "docs": {}}
        self.write_config(root, config)
        write_file(
            root,
            ".sprint/flags.json",
            json.dumps(
                {
                    "active": "1-1",
                    "sprints": {
                        "1-1": {
                            "stage": "TEST",
                            "status": "open",
                            "sprint_dir": "docs/07_plans/w/s",
                            "kind": "code",
                        }
                    },
                }
            )
            + "\n",
        )

        write_exec(root, "tools-b/fake-pass.sh", "\n".join(["#!/bin/bash", 'echo "ok"', "exit 0", ""]))
        write_exec(
            root,
            "tools-a/fake-fail.sh",
            "\n".join(["#!/bin/bash", 'echo "実装が通らない"', "exit 2", ""]),
        )

        blocked = subprocess.run(
            ["bash", os.path.join(HARNESS, "tools", "gate-check.sh"), "TEST"],
            cwd=root,
            env=self.fixture_env(root),
            capture_output=True,
            text=True,
        )
        blocked_out = blocked.stdout + blocked.stderr
        self.assertIn("✓ fake-pass", blocked_out)
        self.assertIn("✗ fake-fail [実装]", blocked_out)
        self.assertIn("GATE BLOCKED", blocked_out)
        self.assertEqual(blocked.returncode, 1)

        # An empty gate definition passes.
        empty = self.base_config(root)
        empty["gateToolsDirs"] = config["gateToolsDirs"]
        empty["gates"] = {"code": {"TEST": []}, "docs": {}}
        self.write_config(root, empty)
        passed = subprocess.run(
            ["bash", os.path.join(HARNESS, "tools", "gate-check.sh"), "TEST"],
            cwd=root,
            env=self.fixture_env(root),
            capture_output=True,
            text=True,
        )
        self.assertIn("no checks defined — pass", passed.stdout + passed.stderr)
        self.assertEqual(passed.returncode, 0)

    def test_size_audit_tdd_exists_and_spec_graph_read_config_globs(self):
        root = self.mk_root()
        self.write_config(root, self.base_config(root))

        # ── size-audit: scan target is src minus tests ──
        big_lines = "\n".join(f"const x{i} = {i}" for i in range(1201)) + "\n"
        write_file(root, "app/src/big.ts", big_lines)
        write_file(root, "app/src/big.test.ts", big_lines)

        size_audit = subprocess.run(
            ["bash", os.path.join(HARNESS, "gate-tools", "size-audit.sh")],
            cwd=root,
            env=self.fixture_env(root),
            capture_output=True,
            text=True,
        )
        size_out = size_audit.stdout + size_audit.stderr
        self.assertIn("app/src/big.ts", size_out)
        self.assertNotIn("big.test.ts", size_out)
        self.assertEqual(size_audit.returncode, 1)

        # ── a test file that matches the tests glob (referenced below). Its
        # test name embeds a synthetic Test ID (tdd-exists looks these up in
        # test source) and a clause reference [[XX-1]] (spec-graph looks
        # these up as edges) — both are generic fixture placeholders, not
        # identifiers from this test file itself. ──
        spec_lines = [
            "import { test, expect } from '@playwright/test'",
            "",
            "test('TEST-1-1-1.1 [[XX-1]] fixture confirmation', async () => {",
            "  expect(1).toBe(1)",
            "})",
            "",
        ]
        write_file(root, "ui/e2e/a.spec.ts", "\n".join(spec_lines))
        spec_test_line = next(
            i for i, l in enumerate(spec_lines) if l.startswith("test('TEST-1-1-1.1")
        ) + 1

        other_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('[[XX-1]] does not match any tests glob', () => {",
            "  it('TEST-1-1-1.1 mention', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "other/z.test.ts", "\n".join(other_lines))

        # ── tdd-exists: Test IDs are looked up in the tests-glob files ──
        test_md = write_file(
            root,
            "docs/07_plans/w/s/TEST.md",
            "\n".join(
                [
                    "# TEST — fixture",
                    "",
                    "| Test ID | Spec | Test file | Description |",
                    "|---------|------|-----------|-------------|",
                    "| TEST-1-1-1.1 | N-1.1 | ui/e2e/a.spec.ts | fixture confirmation |",
                    "",
                ]
            ),
        )
        write_file(
            root,
            ".sprint/flags.json",
            json.dumps(
                {
                    "active": "1-1",
                    "sprints": {
                        "1-1": {
                            "stage": "BUILD",
                            "status": "open",
                            "sprint_dir": "docs/07_plans/w/s",
                            "kind": "code",
                        }
                    },
                }
            )
            + "\n",
        )

        tdd_exists = subprocess.run(
            ["bash", os.path.join(HARNESS, "gate-tools", "tdd-exists.sh")],
            cwd=root,
            env=self.fixture_env(root, {"TDD_TEST_MD": test_md}),
            capture_output=True,
            text=True,
        )
        self.assertIn("1/1", tdd_exists.stdout + tdd_exists.stderr)
        self.assertEqual(tdd_exists.returncode, 0)

        # ── spec-graph: the test-file set is built from the tests glob ──
        write_file(
            root,
            "docs/05_specifications/x.md",
            "\n".join(
                ["---", "xref-prefix: XX", "---", "# X", "", "## [XX-1] Clause 1", "", "Body 1.", ""]
            ),
        )

        def git(args):
            return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)

        git(["init", "-q"])
        git(["add", "-A"])
        git(["-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init"])

        spec_graph = subprocess.run(
            ["bash", os.path.join(HARNESS, "tools", "spec-graph.sh"), "index"],
            cwd=root,
            env=self.fixture_env(root, {"SPEC_GRAPH_ROOT": root}),
            capture_output=True,
            text=True,
        )
        self.assertEqual(spec_graph.returncode, 0)
        data = json.loads(spec_graph.stdout)
        self.assertEqual(
            [e for e in data["edges"] if e["fromFile"] == "ui/e2e/a.spec.ts"],
            [{"from": None, "fromFile": "ui/e2e/a.spec.ts", "line": spec_test_line, "to": "XX-1"}],
        )
        self.assertEqual([e for e in data["edges"] if e["fromFile"] == "other/z.test.ts"], [])


class SprintNewTemplatesTests(RunnerFixtureMixin, HarnessTestCase):
    """harness/bin/sprint new — templates."""

    def test_new_copies_templates_from_config_and_initializes_flags(self):
        root = self.mk_root()
        self.write_config(root, self.base_config(root))
        write_file(root, "tpl/README.md", "# TPL-README\n")
        write_file(root, "tpl/SPEC.md", "# TPL-SPEC\n")
        write_file(root, "tpl/TEST.md", "# TPL-TEST\n")

        created = self.run_sprint(root, ["new", "1-1", "docs/07_plans/w/s"])
        self.assertEqual(created.returncode, 0)

        with open(os.path.join(root, "docs/07_plans/w/s/README.md"), encoding="utf-8") as f:
            self.assertIn("TPL-README", f.read())
        with open(os.path.join(root, "docs/07_plans/w/s/SPEC.md"), encoding="utf-8") as f:
            self.assertIn("TPL-SPEC", f.read())
        with open(os.path.join(root, "docs/07_plans/w/s/TEST.md"), encoding="utf-8") as f:
            self.assertIn("TPL-TEST", f.read())

        with open(os.path.join(root, ".sprint/flags.json"), encoding="utf-8") as f:
            flags = json.load(f)
        self.assertEqual(flags["active"], "1-1")
        self.assertEqual(flags["sprints"]["1-1"]["stage"], "PLAN")

        # Missing templates directory exits 4.
        no_tpl = self.mk_root()
        self.write_config(no_tpl, self.base_config(no_tpl))
        missing = self.run_sprint(no_tpl, ["new", "1-1", "docs/07_plans/w/s"])
        self.assertIn("templates が無い: ", missing.stdout + missing.stderr)
        self.assertEqual(missing.returncode, 4)


class SetContractDefaultsTests(RunnerFixtureMixin, HarnessTestCase):
    """Set contracts — reading config defaults.

    Note: the original source test also exercised a project-specific
    `accounts.sh` set-contract tool (scripts/gate-tools/project/accounts.sh).
    That tool is part of the private source project, not the generalized
    harness being ported here, so only the api-routes portion is ported.
    """

    def test_api_routes_reads_sets_impl_cmd_and_spec_dir_from_config(self):
        root = self.mk_root()
        config = self.base_config(root)
        impl_json = os.path.join(root, "impl.json")
        config["sets"] = {"routes": {"implCmd": f'cat "{impl_json}"'}}
        self.write_config(root, config)

        with open(impl_json, "w", encoding="utf-8") as f:
            json.dump([{"method": "GET", "path": "/a"}], f)
            f.write("\n")
        write_file(root, "spec/x.md", "\n".join(["# Spec", "", "- `GET /a` returns a list.", ""]))

        def run_verify():
            return subprocess.run(
                ["bash", os.path.join(HARNESS, "tools", "api-routes.sh"), "verify"],
                cwd=root,
                env=self.fixture_env(root),
                capture_output=True,
                text=True,
            )

        # No env var override: sets.routes.implCmd and docs.specDir are used.
        same = run_verify()
        self.assertNotIn("api-routes:", same.stdout + same.stderr)
        self.assertEqual(same.returncode, 0)

        # Implementation has a route the spec doesn't → exit 1.
        with open(impl_json, "w", encoding="utf-8") as f:
            json.dump([{"method": "GET", "path": "/a"}, {"method": "GET", "path": "/b"}], f)
            f.write("\n")
        self.assertEqual(run_verify().returncode, 1)


class SizeAuditFixtureMixin:
    """Fixture builders for the size-audit two-tier threshold tests."""

    def make_temp_root(self):
        root = self.mk_root()
        os.makedirs(os.path.join(root, "backend", "src"), exist_ok=True)
        os.makedirs(os.path.join(root, "frontend", "src"), exist_ok=True)
        # Minimal config: size-audit.sh only needs schemaVersion (for
        # sprint_config_require) and components[*].src/tests globs.
        config = {
            "schemaVersion": 1,
            "components": {
                "backend": {"src": ["backend/src/**"], "tests": []},
                "frontend": {"src": ["frontend/src/**"], "tests": []},
            },
        }
        write_file(root, "sprint.config.json", json.dumps(config, indent=2) + "\n")
        return root

    def write_dummy_file(self, root, rel_path, line_count):
        content = "\n".join(f"// dummy line {i + 1}" for i in range(line_count)) + "\n"
        write_file(root, rel_path, content)

    def run_size_audit(self, root, overrides):
        env = shell_env()
        for key in ("SPRINT_GATE", "SIZE_WARN", "SIZE_LIMIT", "SIZE_AUDIT_ROOT"):
            env.pop(key, None)
        env["CLAUDE_PROJECT_DIR"] = root
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            ["bash", os.path.join(HARNESS, "gate-tools", "size-audit.sh")],
            env=env,
            capture_output=True,
            text=True,
        )


class SizeAuditTwoTierThresholdTests(SizeAuditFixtureMixin, HarnessTestCase):
    """harness/gate-tools/size-audit.sh — two-tier warn/reject thresholds."""

    def test_warn_band_exits_0_under_gate_and_thresholds_are_configurable(self):
        # Default thresholds (800/1200): lower boundary 801, upper boundary 1200.
        root = self.make_temp_root()
        self.write_dummy_file(root, "backend/src/warn-lower-801.ts", 801)
        self.write_dummy_file(root, "frontend/src/warn-upper-1200.ts", 1200)

        result = self.run_size_audit(root, {"SPRINT_GATE": "1", "SIZE_AUDIT_ROOT": root})

        self.assertEqual(result.returncode, 0)
        self.assertIn("warn-lower-801.ts", result.stdout)
        self.assertIn("warn-upper-1200.ts", result.stdout)
        # Default SIZE_WARN=800, 2 files over it.
        self.assertIn("800 行超過 2 件", result.stdout)

        # A custom SIZE_WARN makes a smaller file count as warn-band.
        warn_root = self.make_temp_root()
        self.write_dummy_file(warn_root, "backend/src/custom-warn-75.ts", 75)

        result = self.run_size_audit(
            warn_root,
            {
                "SPRINT_GATE": "1",
                "SIZE_AUDIT_ROOT": warn_root,
                "SIZE_WARN": "50",
                "SIZE_LIMIT": "100",
            },
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("custom-warn-75.ts", result.stdout)

        # A custom SIZE_LIMIT rejects a file that would be warn-band by default.
        limit_root = self.make_temp_root()
        self.write_dummy_file(limit_root, "backend/src/custom-reject-150.ts", 150)

        result = self.run_size_audit(
            limit_root,
            {
                "SPRINT_GATE": "1",
                "SIZE_AUDIT_ROOT": limit_root,
                "SIZE_WARN": "50",
                "SIZE_LIMIT": "100",
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("custom-reject-150.ts", result.stdout)

    def test_reject_band_exits_2_under_gate_and_lists_files_by_line_count_desc(self):
        root = self.make_temp_root()
        # Reject-band boundary 1201, plus larger files, to verify descending order.
        self.write_dummy_file(root, "backend/src/reject-a-2000.ts", 2000)
        self.write_dummy_file(root, "backend/src/reject-b-1500.ts", 1500)
        self.write_dummy_file(root, "frontend/src/reject-c-1201.ts", 1201)
        # A warn-band file mixed in must not break the descending order.
        self.write_dummy_file(root, "frontend/src/warn-d-900.ts", 900)

        result = self.run_size_audit(root, {"SPRINT_GATE": "1", "SIZE_AUDIT_ROOT": root})

        self.assertEqual(result.returncode, 2)
        # Default SIZE_LIMIT=1200, 3 files over it.
        self.assertIn("size over 1200 lines: 3 file(s)", result.stdout)

        idx_a = result.stdout.find("reject-a-2000.ts")
        idx_b = result.stdout.find("reject-b-1500.ts")
        idx_c = result.stdout.find("reject-c-1201.ts")

        self.assertGreaterEqual(idx_a, 0)
        self.assertGreaterEqual(idx_b, 0)
        self.assertGreaterEqual(idx_c, 0)
        self.assertLess(idx_a, idx_b)
        self.assertLess(idx_b, idx_c)

    def test_no_files_over_warn_threshold_exits_0_regardless_of_gate(self):
        root = self.make_temp_root()
        # Exactly at the warn threshold stays on the safe side.
        self.write_dummy_file(root, "backend/src/ok-800.ts", 800)
        self.write_dummy_file(root, "frontend/src/ok-small.ts", 10)

        gated = self.run_size_audit(root, {"SPRINT_GATE": "1", "SIZE_AUDIT_ROOT": root})
        self.assertEqual(gated.returncode, 0)
        self.assertIn("ok: no file over 800 lines", gated.stdout)

        ungated = self.run_size_audit(root, {"SIZE_AUDIT_ROOT": root})
        self.assertEqual(ungated.returncode, 0)
        self.assertIn("ok: no file over 800 lines", ungated.stdout)

    def test_manual_run_without_gate_exits_1_when_any_file_exceeds_warn(self):
        # Warn-band only.
        warn_root = self.make_temp_root()
        self.write_dummy_file(warn_root, "backend/src/warn-only-900.ts", 900)

        result = self.run_size_audit(warn_root, {"SIZE_AUDIT_ROOT": warn_root})
        self.assertEqual(result.returncode, 1)
        # Only the temp dir should be in scope (no accidental match against
        # some other project's pre-existing oversized files).
        self.assertIn("warn-only-900.ts", result.stdout)

        # Reject-band also exits 1 when run manually.
        reject_root = self.make_temp_root()
        self.write_dummy_file(reject_root, "backend/src/reject-only-1500.ts", 1500)

        result = self.run_size_audit(reject_root, {"SIZE_AUDIT_ROOT": reject_root})
        self.assertEqual(result.returncode, 1)
        self.assertIn("reject-only-1500.ts", result.stdout)


if __name__ == "__main__":
    unittest.main()
