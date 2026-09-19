"""Tests for harness/lib/config.sh, config.py, env.sh, and the
harness/hooks/edit-scope-gate.sh + scope-lib.sh write-scope gate.

Ported from the original TypeScript/vitest test suite to Python 3 standard
library only (unittest + tempfile + subprocess), so the harness's own
regression tests can run with just python3/bash/jq/git installed.

Fixtures are built from scratch in a temporary directory for every test
(via ``CLAUDE_PROJECT_DIR=<root>``) and do not depend on any file from the
project this harness was copied out of. ``<root>/sprint.config.json`` is
the fixture's config; ``SPRINT_CONFIG`` is left unset so the default path
is used.
"""
import atexit
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# Repository root: three levels above this file (harness/tests/test_config.py
# -> harness/tests -> harness -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_gnu_date():
    """Return the path to a GNU coreutils `date` binary, or None.

    harness/lib/env.sh's sprint_date() (and callers such as
    harness/bin/sprint's `now()`) shell out to the bare `date` command using
    GNU-only format specifiers (e.g. `%:z`). On a plain BSD/macOS system the
    default `date` does not support those, but a GNU one is commonly
    available as `gdate` (e.g. via Homebrew's coreutils). Prefer whichever
    `date` on PATH is already GNU; fall back to `gdate` if present.
    """
    for candidate in ("date", "gdate"):
        exe = shutil.which(candidate)
        if not exe:
            continue
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        except OSError:
            continue
        if out.returncode == 0 and "GNU coreutils" in out.stdout:
            return exe
    return None


_GNU_DATE_SHIM_DIR = None


def _gnu_date_path_prefix():
    """A PATH directory to prepend so plain `date` resolves to a GNU date,
    or "" if the default `date` is already GNU (typical on Linux) or no GNU
    date is available at all."""
    global _GNU_DATE_SHIM_DIR
    if _GNU_DATE_SHIM_DIR is None:
        gnu_date = _find_gnu_date()
        if gnu_date is None or os.path.basename(gnu_date) == "date":
            _GNU_DATE_SHIM_DIR = ""
        else:
            shim_dir = tempfile.mkdtemp(prefix="csp-harness-config-gnu-date-")
            os.symlink(gnu_date, os.path.join(shim_dir, "date"))
            atexit.register(shutil.rmtree, shim_dir, ignore_errors=True)
            _GNU_DATE_SHIM_DIR = shim_dir
    return _GNU_DATE_SHIM_DIR


def write_file(root: Path, rel_path: str, content: str) -> Path:
    """Write a file under root, creating parent directories as needed."""
    file_path = root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def base_config(root: Path) -> dict:
    """Minimal fixture config: two components, app (role backend) and ui
    (role frontend)."""
    return {
        "schemaVersion": 1,
        "project": {"name": "fixture", "timezone": "Asia/Tokyo"},
        "docs": {
            "templates": str(root / "tpl"),
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
        "evidence": {"dir": ".sprint/test-result"},
        "sets": {},
        "gateToolsDirs": [str(root / "gate-tools")],
        "gates": {"code": {}, "docs": {}},
    }


def write_config(root: Path, config: dict) -> None:
    write_file(root, "sprint.config.json", json.dumps(config, indent=2) + "\n")


def fixture_env(root: Path, extra: dict = None) -> dict:
    """Environment for a child process: drop the entry-point variables so
    the test runner's own settings don't leak in."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    for key in ("SPRINT_CONFIG", "SPRINT_TZ", "SPRINT_GATE", "SPRINT_ADAPTERS_DIR"):
        env.pop(key, None)
    gnu_date_dir = _gnu_date_path_prefix()
    if gnu_date_dir:
        env["PATH"] = gnu_date_dir + os.pathsep + env.get("PATH", "")
    if extra:
        env.update(extra)
    return env


def run_shell(root: Path, script: str, args, extra_env: dict = None):
    """Source harness/lib/env.sh and run a shell snippet, mirroring the
    original test helper's argument layout ($1 = REPO_ROOT, $2.. = args)."""
    return subprocess.run(
        ["bash", "-c", '. "$1/harness/lib/env.sh"; ' + script, "bash", str(REPO_ROOT), *args],
        cwd=str(root),
        env=fixture_env(root, extra_env),
        capture_output=True,
        text=True,
    )


# Caller (agent_type; "main" means no agent_type in the payload).
ACTORS = ["main", "backend", "frontend", "tester", "qa"]

# Kind, as returned by scope_classify, paired with a sample relative path.
TYPES = [
    ("state", ".sprint/flags.json"),
    ("spec", "docs/07_plans/w/s/SPEC.md"),
    ("testmd", "docs/07_plans/w/s/TEST.md"),
    ("test", "app/src/x.test.ts"),
    ("app", "app/src/x.ts"),
    ("ui", "ui/src/y.tsx"),
    ("other", "README.md"),
]

# The write-scope matrix (source of truth mirrored from scope-lib.sh /
# edit-scope-gate.sh): a component's src is allow only for the caller whose
# agent_type matches that component's role (app = backend, ui = frontend).
# qa x TEST.md is "allow only inside the UNSEAL region".
MATRIX = {
    "main": {"state": "deny", "spec": "allow", "testmd": "allow", "test": "deny", "app": "deny", "ui": "deny", "other": "allow"},
    "backend": {"state": "deny", "spec": "deny", "testmd": "deny", "test": "deny", "app": "allow", "ui": "deny", "other": "allow"},
    "frontend": {"state": "deny", "spec": "deny", "testmd": "deny", "test": "deny", "app": "deny", "ui": "allow", "other": "allow"},
    "tester": {"state": "deny", "spec": "deny", "testmd": "deny", "test": "allow", "app": "deny", "ui": "deny", "other": "allow"},
    "qa": {"state": "deny", "spec": "deny", "testmd": "unseal", "test": "deny", "app": "deny", "ui": "deny", "other": "allow"},
}

UNSEAL_TEXT = "unsealed content line B"
SEALED_TEXT = "sealed content line A"


def run_edit(root: Path, actor: str, file_path: str, old_string: str, new_string: str):
    """Feed an Edit tool call to harness/hooks/edit-scope-gate.sh."""
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": old_string, "new_string": new_string},
    }
    if actor != "main":
        payload["agent_type"] = actor
    return subprocess.run(
        ["bash", str(REPO_ROOT / "harness" / "hooks" / "edit-scope-gate.sh")],
        cwd=str(root),
        env=fixture_env(root),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="csp-harness-config-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- config.sh: sprint_config reads a value from the config -------------

    def test_config_reads_role_via_jq_filter(self):
        write_config(self.root, base_config(self.root))
        write_file(self.root, ".sprint/flags.json", json.dumps({"active": ""}) + "\n")

        role = run_shell(self.root, 'sprint_config "$2"', [".components.app.role"])
        self.assertEqual(role.returncode, 0)
        self.assertEqual(role.stdout.strip(), "backend")

    # -- config.sh / bin/sprint: unsupported schemaVersion is rejected -----

    def test_unsupported_schema_version_fails_with_exit_code_4(self):
        write_config(self.root, base_config(self.root))
        write_file(self.root, ".sprint/flags.json", json.dumps({"active": ""}) + "\n")

        bad = base_config(self.root)
        bad["schemaVersion"] = 2
        write_config(self.root, bad)

        status = subprocess.run(
            ["bash", str(REPO_ROOT / "harness" / "bin" / "sprint"), "status"],
            cwd=str(self.root),
            env=fixture_env(self.root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(status.returncode, 4)
        self.assertIn(
            "sprint.config.json の schemaVersion 2 は対応外（対応 1）",
            status.stdout + status.stderr,
        )

    # -- env.sh: SPRINT_TZ defaults to project.timezone, env var overrides -

    def test_timezone_defaults_to_project_config_and_env_var_overrides(self):
        write_config(self.root, base_config(self.root))
        write_file(self.root, ".sprint/flags.json", json.dumps({"active": ""}) + "\n")

        utc = base_config(self.root)
        utc["project"]["timezone"] = "UTC"
        write_config(self.root, utc)

        default_tz = run_shell(self.root, "sprint_date +%:z", [])
        self.assertEqual(default_tz.returncode, 0)
        self.assertEqual(default_tz.stdout.strip(), "+00:00")

        overridden_tz = run_shell(self.root, "sprint_date +%:z", [], {"SPRINT_TZ": "Asia/Tokyo"})
        self.assertEqual(overridden_tz.returncode, 0)
        self.assertEqual(overridden_tz.stdout.strip(), "+09:00")

    # -- config.sh vs config.py: glob matching agrees between both --------

    def test_glob_match_agrees_between_bash_and_python(self):
        write_config(self.root, base_config(self.root))

        # ** crosses directory boundaries; * and ? do not.
        cases = [
            ("app/src/**", "app/src/a/b.ts", True),
            ("app/src/*.ts", "app/src/a/b.ts", False),
            ("app/src/**/*.test.ts", "app/src/x.test.ts", True),
            ("ui/e2e/**/*.spec.ts", "ui/e2e/a.spec.ts", True),
            ("app/src/**", "apps/src/x.ts", False),
            ("a/?.ts", "a/b.ts", True),
            ("a/?.ts", "a/bc.ts", False),
        ]

        actual = []
        for glob, target, _expected in cases:
            sh = run_shell(self.root, 'sprint_glob_match "$2" "$3"', [glob, target])
            py = subprocess.run(
                ["python3", str(REPO_ROOT / "harness" / "lib" / "config.py"), "glob-match", glob, target],
                cwd=str(self.root),
                env=fixture_env(self.root),
                capture_output=True,
                text=True,
            )
            actual.append({
                "glob": glob,
                "target": target,
                "bash": sh.returncode == 0,
                "python": py.returncode == 0,
            })

        expected = [
            {"glob": glob, "target": target, "bash": expected_bool, "python": expected_bool}
            for glob, target, expected_bool in cases
        ]
        self.assertEqual(actual, expected)

    # -- edit-scope-gate.sh / scope-lib.sh: the full write-scope matrix ----

    def test_edit_scope_gate_matches_the_write_scope_matrix(self):
        write_config(self.root, base_config(self.root))

        write_file(self.root, ".sprint/flags.json", json.dumps({"active": "w-s"}) + "\n")
        write_file(self.root, "docs/07_plans/w/s/SPEC.md", "# SPEC\n")
        write_file(
            self.root,
            "docs/07_plans/w/s/TEST.md",
            "\n".join(
                [
                    "# TEST",
                    "",
                    SEALED_TEXT,
                    "",
                    "<!-- UNSEAL:BEGIN -->",
                    UNSEAL_TEXT,
                    "<!-- UNSEAL:END -->",
                    "",
                    "sealed content line C",
                    "",
                ]
            ),
        )
        write_file(self.root, "app/src/x.test.ts", "import { it } from 'vitest'\n")
        write_file(self.root, "app/src/x.ts", "export const x = 1\n")
        write_file(self.root, "ui/src/y.tsx", "export const Y = 1\n")
        write_file(self.root, "README.md", "# readme\n")

        # -- 35 combinations (5 callers x 7 kinds) must match the matrix --
        decisions = []
        reasons = {}

        for actor in ACTORS:
            for type_key, rel_path in TYPES:
                # qa x TEST.md uses an old_string inside the UNSEAL region
                # (the only allowed sample for "unseal only").
                use_unseal = type_key == "testmd" and MATRIX[actor][type_key] == "unseal"
                old_string = UNSEAL_TEXT if use_unseal else "x"
                result = run_edit(self.root, actor, str(self.root / rel_path), old_string, old_string + "!")
                stdout = result.stdout.strip()
                if stdout == "":
                    decisions.append({"actor": actor, "type": type_key, "decision": "allow"})
                else:
                    out = json.loads(stdout)
                    decision = out["hookSpecificOutput"]["permissionDecision"]
                    decisions.append({"actor": actor, "type": type_key, "decision": decision})
                    reasons[f"{actor}:{type_key}"] = out["hookSpecificOutput"]["permissionDecisionReason"]

        expected = [
            {
                "actor": d["actor"],
                "type": d["type"],
                "decision": "allow" if MATRIX[d["actor"]][d["type"]] == "unseal" else MATRIX[d["actor"]][d["type"]],
            }
            for d in decisions
        ]
        self.assertEqual(decisions, expected)

        # Every deny carries a reason (the wording isn't specified, only
        # that it's non-empty).
        denied = [d for d in decisions if d["decision"] == "deny"]
        self.assertGreater(len(denied), 0)
        for d in denied:
            self.assertNotEqual(reasons.get(f"{d['actor']}:{d['type']}", ""), "")

        # -- qa x TEST.md UNSEAL boundary: the sealed region is denied --
        sealed_edit = run_edit(
            self.root,
            "qa",
            str(self.root / "docs/07_plans/w/s/TEST.md"),
            SEALED_TEXT,
            SEALED_TEXT + "!",
        )
        self.assertNotEqual(sealed_edit.stdout.strip(), "")
        sealed_out = json.loads(sealed_edit.stdout)
        self.assertEqual(sealed_out["hookSpecificOutput"]["permissionDecision"], "deny")

        # -- without a config, hooks pass through undecided (no config) --
        (self.root / "sprint.config.json").unlink()
        passthrough = []
        for actor in ACTORS:
            for type_key, rel_path in TYPES:
                result = run_edit(self.root, actor, str(self.root / rel_path), "x", "x!")
                passthrough.append({
                    "actor": actor,
                    "type": type_key,
                    "stdout": result.stdout.strip(),
                    "status": result.returncode,
                })

        expected_passthrough = [
            {"actor": p["actor"], "type": p["type"], "stdout": "", "status": 0} for p in passthrough
        ]
        self.assertEqual(passthrough, expected_passthrough)


if __name__ == "__main__":
    unittest.main()
