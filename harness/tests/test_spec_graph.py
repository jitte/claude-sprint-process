"""Tests for harness/tools/spec-graph.py / spec-graph.sh and the
harness/gate-tools/spec-lint.sh `refs` check.

Ported from three original TypeScript/vitest test suites into this single
Python 3 standard library file (unittest + tempfile + subprocess), per an
explicit instruction to merge them, so the harness's own regression tests
can run with just python3/bash/jq/git installed:

  - spec-graph.test.ts            -- verify (V1, V2, V3, V5, V6, V8, V9,
                                      V10, V11) and the index / reverse /
                                      diff / resolve / files / layers
                                      subcommands
  - spec-graph-test-refs.test.ts  -- how spec-graph treats references made
                                      from test file names (the [[ID]] scan
                                      inside describe/it/test names)
  - spec-refs.test.ts             -- harness/gate-tools/spec-lint.sh refs
                                      (the "0. referenced common clauses"
                                      table format check)

Fixture corpora are built from scratch in a temporary directory for every
test and do not depend on any file from the project this harness was
copied out of. Condition ID prefixes are generic placeholders (AAA, BBB,
CCC, ... / XX / RULE) invented for each fixture rather than reused from
the source project's domain vocabulary. Where a tool's own output text or
a hard-coded document alias (e.g. the V11 section-reference regex) is in
Japanese, assertions and fixture fragments keep that Japanese verbatim
because it is the literal behavior under test, not project vocabulary.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# Repository root: two levels above this file (harness/tests/test_spec_graph.py
# -> harness/tests -> harness -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]

SPEC_GRAPH_SH = REPO_ROOT / "harness" / "tools" / "spec-graph.sh"
SPEC_LINT_SH = REPO_ROOT / "harness" / "gate-tools" / "spec-lint.sh"


def write_sprint_config(root: Path) -> None:
    """Minimal sprint.config.json placed directly under the fixture root.

    spec-graph.py reads docs.livingDirs / docs.sprintRoot / docs.templates
    and components[*].tests from the config found at the scan root
    (harness/lib/config.py's load()). The layout mirrors the one this
    harness documents for its own projects. A .gitignore with
    `node_modules/` lets fixtures exercise the "ignored directories are
    not scanned" behavior.
    """
    config = {
        "schemaVersion": 1,
        "project": {"name": "fixture", "timezone": "Asia/Tokyo"},
        "docs": {
            "templates": "docs/06_process/templates",
            "livingDirs": [
                "docs/01_overview",
                "docs/02_requirements",
                "docs/03_design",
                "docs/04_standards",
                "docs/05_specifications",
                "docs/06_process",
                "docs/80_references",
                "docs/90_deliverables",
            ],
            "sprintRoot": "docs/07_plans",
            "specDir": "docs/05_specifications",
        },
        "tasks": [],
        "components": {
            "backend": {"tests": ["backend/src/**/*.test.ts"]},
            "frontend": {"tests": ["frontend/src/**/*.test.ts", "frontend/src/**/*.test.tsx"]},
            "e2e": {"tests": ["frontend/tests/**/*.spec.ts"]},
        },
        "evidence": {"dir": ".sprint/test-result"},
        "sets": {},
        "gateToolsDirs": [],
        "gates": {},
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "sprint.config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")


def write_file(root: Path, rel_path: str, content: str) -> Path:
    """Write a file under root, creating parent directories as needed."""
    file_path = root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def write_spec_hashes(root: Path, sealed_rel_paths) -> None:
    """Write .sprint/spec-hashes.json (the seal list). The hash values
    themselves don't matter to spec-graph.py -- only the set of keys
    (sealed relative paths) does."""
    obj = {p: "0" * 64 for p in sealed_rel_paths}
    write_file(root, ".sprint/spec-hashes.json", json.dumps(obj, indent=2))


def write_x_doc(root: Path) -> None:
    """docs/05_specifications/x.md declaring xref-prefix XX with two
    clauses, XX-1 and XX-2, and no cross-references of its own. Shared by
    the test-file-reference fixtures below."""
    write_file(
        root,
        "docs/05_specifications/x.md",
        "\n".join(
            [
                "---",
                "xref-prefix: XX",
                "---",
                "# X",
                "",
                "## [XX-1] Clause 1",
                "",
                "Body 1.",
                "",
                "## [XX-2] Clause 2",
                "",
                "Body 2.",
                "",
            ]
        ),
    )


def run_spec_graph(root: Path, args, overrides=None):
    """Run spec-graph.sh as a subprocess against the fixture root."""
    env = dict(os.environ)
    env["SPEC_GRAPH_ROOT"] = str(root)
    if overrides:
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    return subprocess.run(
        ["bash", str(SPEC_GRAPH_SH), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def run_spec_refs(spec_path, root: Path):
    """Run spec-lint.sh refs against a fixture SPEC.md. CLAUDE_PROJECT_DIR
    points sprint_root() at the fixture root (which has its own
    sprint.config.json) so spec_config_require succeeds without touching
    any real project; SPEC_REFS_TARGET points check_refs at the fixture
    SPEC.md directly, so the active-sprint lookup in flags.json is never
    exercised."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["SPEC_REFS_TARGET"] = str(spec_path)
    return subprocess.run(
        ["bash", str(SPEC_LINT_SH), "refs"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def git(root: Path, args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8"
    )


def git_commit(root: Path, message: str):
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=tester@example.com",
            "-c",
            "user.name=Test Runner",
            "commit",
            "-m",
            message,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def hash_dir(root: Path) -> str:
    """SHA-256 over every file under root (relative path + raw content), in
    a deterministic order. Used to check that `resolve` does not rewrite
    its input files (it must only print, never edit)."""
    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            files.append(os.path.join(dirpath, fn))
    files.sort()

    h = hashlib.sha256()
    for f in files:
        rel = os.path.relpath(f, root)
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with open(f, "rb") as fh:
            h.update(fh.read())
        h.update(b"\0")
    return h.hexdigest()


def count_occurrences(haystack: str, needle: str) -> int:
    """Non-overlapping occurrence count. Used to check "exactly once"."""
    return haystack.count(needle)


class SpecGraphFixture(unittest.TestCase):
    """Base fixture: a temp root with a minimal sprint.config.json, cleaned
    up in tearDown. Every test builds its own fixture corpus on top of
    this via mk_root()."""

    def setUp(self):
        self._roots = []

    def tearDown(self):
        for root in self._roots:
            shutil.rmtree(root, ignore_errors=True)

    def mk_root(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="csp-spec-graph-")).resolve()
        write_sprint_config(root)
        self._roots.append(root)
        return root


class SpecGraphVerifyTests(SpecGraphFixture):
    """`verify`'s core checks: V1 (prefix uniqueness), V2 (clause ID
    uniqueness), V3 (reference existence), V5 (impl path existence), V6
    (frontmatter), and that a sealed sprint SPEC is exempt from V3."""

    def test_verify_passes_with_no_violations(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/overview.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: AAA",
                    "layer: common",
                    "---",
                    "# Overview",
                    "",
                    "## [AAA-1] Overview",
                    "",
                    "THE system SHALL derive views from records and entries.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "THE Core aggregate SHALL verify debit/credit balance. "
                    "Time handling follows [[BBB-1]].",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/supporting.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: supporting",
                    "---",
                    "# Supporting",
                    "",
                    "## [DDD-1] Master CRUD",
                    "",
                    "THE system SHALL CRUD masters. Balance handling follows [[CCC-1]].",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/generic.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: EEE",
                    "layer: generic",
                    "---",
                    "# Generic",
                    "",
                    "## [EEE-1] Trial balance",
                    "",
                    "THE system SHALL derive a trial balance. Master resolution follows [[DDD-1]].",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 0)

    def test_v3_detects_reference_to_nonexistent_id(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Timezone",
                    "",
                    "Reference [[BBB-99]] does not exist.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("BBB-99", result.stdout)
        self.assertRegex(result.stdout, r"common-specification\.md:\d+")

    def test_v1_detects_duplicate_prefix(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/duplicate-prefix.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: supporting",
                    "---",
                    "# Duplicate Prefix",
                    "",
                    "## [BBB-2] Another clause",
                    "",
                    "The BBB prefix duplicates common-specification.md.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("common-specification.md", result.stdout)
        self.assertIn("duplicate-prefix.md", result.stdout)

    def test_v2_detects_duplicate_clause_id(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] First clause",
                    "",
                    "Content A.",
                    "",
                    "## [BBB-1] Duplicate clause",
                    "",
                    "Content B.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        positions = re.findall(r"common-specification\.md:\d+", result.stdout)
        self.assertGreaterEqual(len(positions), 2)

    def test_v5_detects_nonexistent_impl_path(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "impl: backend/src/does/not/exist",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)

    def test_sealed_spec_invalid_references_not_verified(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )
        # A sealed sprint SPEC: it has a broken reference [[BBB-99]], but it
        # is listed in spec-hashes.json, so it is out of scope for
        # verification (sealed records are not rewritten).
        write_file(
            root,
            "docs/07_plans/99_dummy/SPEC.md",
            "\n".join(["# SPEC -- Dummy", "", "The balance rule follows [[BBB-99]].", ""]),
        )
        write_spec_hashes(root, ["docs/07_plans/99_dummy/SPEC.md"])

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 0)

    def test_v6_detects_missing_frontmatter_on_base_spec_with_clause_heading(self):
        # A file with a clause heading ([ZZZ-1]) but no frontmatter (so no
        # xref-prefix declaration) is a base spec whose clause would
        # silently fall out of scope; V6 must catch it.
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/no-frontmatter.md",
            "\n".join(
                [
                    "# No Frontmatter",
                    "",
                    "## [ZZZ-1] Heading",
                    "",
                    "A base spec file without frontmatter.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("no-frontmatter.md", result.stdout)
        self.assertIn("V6", result.stdout)

    def test_v6_detects_invalid_layer_value(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: middleware",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)


class SpecGraphSubcommandTests(SpecGraphFixture):
    """`reverse`, `index`, `diff`, and `resolve`."""

    def test_reverse_lists_referencing_locations(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/backend/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "THE Core aggregate SHALL verify debit/credit balance.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/07_plans/99_dummy/SPEC.md",
            "\n".join(["# SPEC -- Dummy", "", "The balance rule follows [[CCC-1]].", ""]),
        )

        result = run_spec_graph(root, ["reverse", "CCC-1"])

        self.assertEqual(result.returncode, 0)
        self.assertIn("99_dummy/SPEC.md", result.stdout)
        self.assertRegex(result.stdout, r"SPEC\.md:\d+")

    def test_index_outputs_nodes_and_edges_as_json(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "Time handling follows [[BBB-1]].",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/supporting.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: supporting",
                    "---",
                    "# Supporting",
                    "",
                    "## [DDD-1] Master CRUD",
                    "",
                    "Balance handling follows [[CCC-1]].",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/generic.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: EEE",
                    "layer: generic",
                    "---",
                    "# Generic",
                    "",
                    "## [EEE-1] Trial balance",
                    "",
                    "Master resolution follows [[DDD-1]].",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["index"])

        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)

        # Clause count (fixture: BBB-1, CCC-1, DDD-1, EEE-1 -- 4 total).
        self.assertIsInstance(data["nodes"], list)
        self.assertEqual(len(data["nodes"]), 4)

        # Reference count (fixture: CCC->BBB, DDD->CCC, EEE->DDD -- 3 total).
        self.assertIsInstance(data["edges"], list)
        self.assertEqual(len(data["edges"]), 3)

        # Every node carries a content hash.
        for node in data["nodes"]:
            self.assertIsInstance(node["hash"], str)
            self.assertGreater(len(node["hash"]), 0)

    def test_diff_outputs_changed_clause_and_referrer(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/backend/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "THE Core aggregate SHALL verify debit/credit balance.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/supporting.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: supporting",
                    "---",
                    "# Supporting",
                    "",
                    "## [DDD-1] Master CRUD",
                    "",
                    "Balance handling follows [[CCC-1]].",
                    "",
                ]
            ),
        )

        init = git(root, ["init", "-q"])
        self.assertEqual(init.returncode, 0)
        add = git(root, ["add", "-A"])
        self.assertEqual(add.returncode, 0)
        commit = git_commit(root, "initial")
        self.assertEqual(commit.returncode, 0)
        rev_parse = git(root, ["rev-parse", "HEAD"])
        self.assertEqual(rev_parse.returncode, 0)
        initial_ref = rev_parse.stdout.strip()

        # Change the CCC-1 clause body (uncommitted -- treated as the
        # current working-tree state).
        write_file(
            root,
            "docs/05_specifications/backend/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "THE Core aggregate SHALL verify debit/credit balance (revised).",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["diff", initial_ref])

        self.assertEqual(result.returncode, 0)
        self.assertIn("CCC-1", result.stdout)
        self.assertIn("supporting.md", result.stdout)

    def test_resolve_outputs_each_reached_clause_once(self):
        root = self.mk_root()

        # Depth-4 chain: sprint SPEC -> frontend -> supporting -> core ->
        # common (a legal chain under the layer permission matrix).
        spec_path = write_file(
            root,
            "docs/07_plans/99_depth4/SPEC.md",
            "\n".join(["# SPEC -- Depth4 Fixture", "", "The screen spec follows [[AAA-1]].", ""]),
        )
        write_file(
            root,
            "docs/05_specifications/frontend/screen.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: AAA",
                    "layer: frontend",
                    "---",
                    "# Journal Screen",
                    "",
                    "## [AAA-1] Journal screen",
                    "",
                    "THE screen SHALL list journal entries. "
                    "Master resolution follows [[BBB-1]].",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/master.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: supporting",
                    "---",
                    "# Master",
                    "",
                    "## [BBB-1] Master CRUD",
                    "",
                    "THE system SHALL CRUD masters. Balance handling follows [[CCC-1]].",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/transaction.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Transaction",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "THE Transaction aggregate SHALL verify debit/credit balance. "
                    "Time handling follows [[DDD-1]].",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [DDD-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )

        before_hash = hash_dir(root)

        result = run_spec_graph(root, ["resolve", str(spec_path)])

        self.assertEqual(result.returncode, 0)

        # The original text is output unchanged: [[AAA-1]] is not replaced.
        self.assertIn("The screen spec follows [[AAA-1]].", result.stdout)

        # The bodies of all 4 reached clauses appear (transitive closure).
        self.assertIn("list journal entries", result.stdout)
        self.assertIn("CRUD masters", result.stdout)
        self.assertIn("verify debit/credit balance", result.stdout)
        self.assertIn("use Asia/Tokyo", result.stdout)

        # Each clause's source (file:line) is listed.
        self.assertRegex(result.stdout, r"screen\.md:\d+")
        self.assertRegex(result.stdout, r"master\.md:\d+")
        self.assertRegex(result.stdout, r"transaction\.md:\d+")
        self.assertRegex(result.stdout, r"common-specification\.md:\d+")

        # Each clause's declaration heading appears exactly once (an
        # already-seen clause is not re-expanded).
        self.assertEqual(count_occurrences(result.stdout, "[AAA-1] Journal screen"), 1)
        self.assertEqual(count_occurrences(result.stdout, "[BBB-1] Master CRUD"), 1)
        self.assertEqual(count_occurrences(result.stdout, "[CCC-1] Balance rule"), 1)
        self.assertEqual(count_occurrences(result.stdout, "[DDD-1] Timezone"), 1)

        # The input files are not rewritten (sha256 of the whole fixture
        # directory matches before and after).
        after_hash = hash_dir(root)
        self.assertEqual(after_hash, before_hash)

    def test_resolve_terminates_cycle_and_exits_zero(self):
        root = self.mk_root()

        # Mutual reference within one file: BBB-1 -> BBB-2 -> BBB-1
        # (common -> common is allowed only within the same file).
        spec_path = write_file(
            root,
            "docs/07_plans/99_cycle/SPEC.md",
            "\n".join(["# SPEC -- Cycle Fixture", "", "The cycle check follows [[BBB-1]].", ""]),
        )
        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: BBB",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [BBB-1] Clause A",
                    "",
                    "Content A. Next see [[BBB-2]].",
                    "",
                    "## [BBB-2] Clause B",
                    "",
                    "Content B. Back to see [[BBB-1]].",
                    "",
                ]
            ),
        )

        before_hash = hash_dir(root)

        result = run_spec_graph(root, ["resolve", str(spec_path)])

        self.assertEqual(result.returncode, 0)

        # The original [[BBB-1]] is left as-is.
        self.assertIn("The cycle check follows [[BBB-1]].", result.stdout)

        # A and B's body and declaration heading each appear exactly once
        # (no infinite expansion).
        self.assertEqual(count_occurrences(result.stdout, "Content A"), 1)
        self.assertEqual(count_occurrences(result.stdout, "Content B"), 1)
        self.assertEqual(count_occurrences(result.stdout, "[BBB-1] Clause A"), 1)
        self.assertEqual(count_occurrences(result.stdout, "[BBB-2] Clause B"), 1)

        # A cycle comment is attached.
        cycle_comment = re.search(r"<!--\s*resolve:\s*cycle[\s\S]*?-->", result.stdout)
        self.assertIsNotNone(cycle_comment)
        self.assertIn("BBB-1", cycle_comment.group(0))
        self.assertIn("BBB-2", cycle_comment.group(0))

        # The input files are not rewritten.
        after_hash = hash_dir(root)
        self.assertEqual(after_hash, before_hash)


class SpecGraphAnchorAndLinkTests(SpecGraphFixture):
    """Clause anchors and markdown-link references: both the `[[ID]]` and
    `[ID](path#ID)` notations are parsed equally, and V8 / V9 validate the
    link's relative path and target anchor."""

    def test_index_parses_both_old_and_new_reference_notations_equally(self):
        # A regression check: a fixture using only [[ID]] and one using
        # only [ID](path#ID) must produce the same number of index edges.
        # Dropping acceptance of the old notation would break references
        # left in sealed historical records.
        root_old = self.mk_root()
        write_file(
            root_old,
            "docs/05_specifications/backend/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "The balance rule references [[DDD-6]].",
                    "",
                ]
            ),
        )

        root_new = self.mk_root()
        write_file(
            root_new,
            "docs/05_specifications/backend/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "The balance rule references [DDD-6](../operations/other.md#DDD-6).",
                    "",
                ]
            ),
        )

        result_old = run_spec_graph(root_old, ["index"])
        result_new = run_spec_graph(root_new, ["index"])

        self.assertEqual(result_old.returncode, 0)
        self.assertEqual(result_new.returncode, 0)

        data_old = json.loads(result_old.stdout)
        data_new = json.loads(result_new.stdout)

        # Both notations parse to the same single reference.
        self.assertGreater(len(data_old["edges"]), 0)
        self.assertEqual(len(data_new["edges"]), len(data_old["edges"]))

    def test_v8_detects_nonexistent_relative_path(self):
        root = self.mk_root()
        write_file(
            root,
            "docs/05_specifications/backend/transaction.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Transaction",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "THE Transaction aggregate SHALL verify debit/credit balance. "
                    "Details are at [CCC-1](../nonexistent/does-not-exist.md#CCC-1).",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("V8", result.stdout)
        self.assertRegex(result.stdout, r"transaction\.md:\d+")

    def test_v9_detects_nonexistent_anchor(self):
        root = self.mk_root()
        write_file(
            root,
            "docs/05_specifications/backend/transaction.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Transaction",
                    "",
                    "## [CCC-1] Balance rule",
                    "",
                    "THE Transaction aggregate SHALL verify debit/credit balance. "
                    "Time handling follows [DDD-1](../common-specification.md#DDD-1).",
                    "",
                ]
            ),
        )
        # The target file exists, but there is no <a id="DDD-1"></a> anchor
        # right before the [DDD-1] heading.
        write_file(
            root,
            "docs/05_specifications/common-specification.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: common",
                    "---",
                    "# Common Specification",
                    "",
                    "## [DDD-1] Timezone",
                    "",
                    "THE system SHALL use Asia/Tokyo.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("V9", result.stdout)
        self.assertRegex(result.stdout, r"transaction\.md:\d+")


class SpecGraphMachineVerificationTests(SpecGraphFixture):
    """V10 (clause reference graph cycles), V11 (stale section-number
    references), and the `files` / `layers` subcommands, plus `index`'s
    edges[].from computation (excluding references made from consumer
    files)."""

    def test_v10_detects_mutual_reference_within_same_file(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/x.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "---",
                    "# X",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause A",
                    "",
                    "Content A. See [CCC-2](#CCC-2) for reference.",
                    "",
                    '<a id="CCC-2"></a>',
                    "## [CCC-2] Clause B",
                    "",
                    "Content B. See [CCC-1](#CCC-1) for reference.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("V10", result.stdout)
        self.assertIn("CCC-1", result.stdout)
        self.assertIn("CCC-2", result.stdout)

    def test_v10_detects_self_reference(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/x.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "---",
                    "# X",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause",
                    "",
                    "Content. Self-reference: [CCC-1](#CCC-1).",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("V10", result.stdout)
        self.assertIn("CCC-1 -> CCC-1", result.stdout)

    def test_v10_detects_cross_file_cycle_and_excludes_consumer_references_from_edges(self):
        # Case A: two files cycle A -> B -> A. exit 1.
        root_cycle = self.mk_root()
        write_file(
            root_cycle,
            "docs/05_specifications/a.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# A",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause A",
                    "",
                    "Content A. See [DDD-1](b.md#DDD-1) for reference.",
                    "",
                ]
            ),
        )
        write_file(
            root_cycle,
            "docs/05_specifications/b.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: supporting",
                    "---",
                    "# B",
                    "",
                    '<a id="DDD-1"></a>',
                    "## [DDD-1] Clause B",
                    "",
                    "Content B. See [CCC-1](a.md#CCC-1) for reference.",
                    "",
                ]
            ),
        )

        result_cycle = run_spec_graph(root_cycle, ["verify"])

        self.assertEqual(result_cycle.returncode, 1)
        self.assertIn("V10", result_cycle.stdout)

        # Case B: move the B -> A reference into a consumer file's table
        # row (no layer, no xref-prefix). Only A -> B remains inside a
        # clause body, so there is no cycle. exit 0.
        root_fixed = self.mk_root()
        write_file(
            root_fixed,
            "docs/05_specifications/a.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# A",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause A",
                    "",
                    "Content A. See [DDD-1](b.md#DDD-1) for reference.",
                    "",
                ]
            ),
        )
        write_file(
            root_fixed,
            "docs/05_specifications/b.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: supporting",
                    "---",
                    "# B",
                    "",
                    '<a id="DDD-1"></a>',
                    "## [DDD-1] Clause B",
                    "",
                    "Content B.",
                    "",
                ]
            ),
        )
        write_file(
            root_fixed,
            "docs/03_design/notes.md",
            "\n".join(
                [
                    "# Notes",
                    "",
                    "| Clause | Description |",
                    "|---|---|",
                    "| [CCC-1](../05_specifications/a.md#CCC-1) | some description |",
                    "",
                ]
            ),
        )

        result_fixed = run_spec_graph(root_fixed, ["verify"])

        self.assertEqual(result_fixed.returncode, 0)

    def test_v11_detects_section_number_reference_and_ignores_code_fences(self):
        # Case A: an ordinary paragraph mentions a section number. exit 1.
        lines_a = [
            "---",
            "xref-prefix: CCC",
            "---",
            "# Y",
            "",
            '<a id="CCC-1"></a>',
            "## [CCC-1] Clause",
            "",
            "The text references `foo.md` §3.2 for details.",
            "",
        ]
        line_no_a = next(i for i, l in enumerate(lines_a) if "foo.md" in l and "§" in l) + 1
        root_a = self.mk_root()
        write_file(root_a, "docs/05_specifications/y.md", "\n".join(lines_a))

        result_a = run_spec_graph(root_a, ["verify"])

        self.assertEqual(result_a.returncode, 1)
        self.assertIn("V11", result_a.stdout)
        self.assertIn(f"y.md:{line_no_a}", result_a.stdout)

        # Case B: the same string only inside a code fence. exit 0.
        root_b = self.mk_root()
        write_file(
            root_b,
            "docs/05_specifications/y2.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "---",
                    "# Y2",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause",
                    "",
                    "```",
                    "`foo.md` §3.2",
                    "```",
                    "",
                ]
            ),
        )

        result_b = run_spec_graph(root_b, ["verify"])

        self.assertEqual(result_b.returncode, 0)

        # Case C: the same string under the templates directory. exit 1.
        lines_c = ["# Z Template", "", "The text references `foo.md` §3.2 for details.", ""]
        line_no_c = next(i for i, l in enumerate(lines_c) if "foo.md" in l and "§" in l) + 1
        root_c = self.mk_root()
        write_file(root_c, "docs/06_process/templates/z.md", "\n".join(lines_c))

        result_c = run_spec_graph(root_c, ["verify"])

        self.assertEqual(result_c.returncode, 1)
        self.assertIn("V11", result_c.stdout)
        self.assertIn(f"z.md:{line_no_c}", result_c.stdout)

    def test_clause_in_design_dir_with_xref_prefix_only_can_be_referenced_from_specifications(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/03_design/design-note.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "---",
                    "# X",
                    "",
                    '<a id="DDD-1"></a>',
                    "## [DDD-1] Design item",
                    "",
                    "THE system SHALL do something.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/y.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: supporting",
                    "---",
                    "# Y",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause",
                    "",
                    "Reference follows [DDD-1](../03_design/design-note.md#DDD-1).",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 0)
        self.assertIn("verify: OK (2 clauses, 1 refs, 2 files)", result.stdout)

    def test_layer_reference_without_parent_hierarchy_passes_and_invalid_layer_fails(self):
        core_content = "\n".join(
            [
                "---",
                "xref-prefix: CCC",
                "layer: core",
                "---",
                "# Core",
                "",
                '<a id="CCC-1"></a>',
                "## [CCC-1] Balance rule",
                "",
                "THE system SHALL verify debit/credit balance.",
                "",
            ]
        )
        frontend_content = "\n".join(
            [
                "---",
                "xref-prefix: DDD",
                "layer: frontend",
                "---",
                "# Frontend",
                "",
                '<a id="DDD-1"></a>',
                "## [DDD-1] Screen",
                "",
                "THE screen SHALL list entries. Balance rule follows [CCC-1](core.md#CCC-1).",
                "",
            ]
        )

        root_ok = self.mk_root()
        write_file(root_ok, "docs/05_specifications/core.md", core_content)
        write_file(root_ok, "docs/05_specifications/frontend.md", frontend_content)

        result_ok = run_spec_graph(root_ok, ["verify"])

        self.assertEqual(result_ok.returncode, 0)

        root_bogus = self.mk_root()
        write_file(root_bogus, "docs/05_specifications/core.md", core_content)
        write_file(root_bogus, "docs/05_specifications/frontend.md", frontend_content)
        write_file(
            root_bogus,
            "docs/05_specifications/bogus.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: EEE",
                    "layer: bogus",
                    "---",
                    "# Bogus",
                    "",
                    '<a id="EEE-1"></a>',
                    "## [EEE-1] Something",
                    "",
                    "Some content.",
                    "",
                ]
            ),
        )

        result_bogus = run_spec_graph(root_bogus, ["verify"])

        self.assertEqual(result_bogus.returncode, 1)

    def test_files_lists_clause_files_and_tree_exits_with_usage(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/README.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: RULE",
                    "---",
                    "# README",
                    "",
                    '<a id="RULE-1"></a>',
                    "## [RULE-1] Some rule",
                    "",
                    "THE system SHALL follow some rule.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/backend/item.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Item",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Balance rule",
                    "",
                    "THE system SHALL verify debit/credit balance. "
                    "Reference follows [RULE-1](../README.md#RULE-1).",
                    "",
                ]
            ),
        )

        files_result = run_spec_graph(root, ["files"])

        self.assertEqual(files_result.returncode, 0)
        readme_line = next(
            (l for l in files_result.stdout.split("\n") if "README.md" in l), None
        )
        self.assertIsNotNone(readme_line)
        self.assertIn("RULE", readme_line)
        self.assertRegex(readme_line, r"(^|\s)-(\s|$)")
        item_line = next((l for l in files_result.stdout.split("\n") if "item.md" in l), None)
        self.assertIsNotNone(item_line)
        self.assertIn("CCC", item_line)
        self.assertIn("core", item_line)

        tree_result = run_spec_graph(root, ["tree"])

        self.assertEqual(tree_result.returncode, 2)

    def test_layers_outputs_layer_by_layer_reference_counts(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/core.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# Core",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Balance rule",
                    "",
                    "THE system SHALL verify debit/credit balance.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/sup1.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: EEE",
                    "layer: supporting",
                    "---",
                    "# Sup A",
                    "",
                    '<a id="EEE-1"></a>',
                    "## [EEE-1] Support A",
                    "",
                    "Content. Balance rule follows [CCC-1](core.md#CCC-1).",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/sup2.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: FFF",
                    "layer: supporting",
                    "---",
                    "# Sup B",
                    "",
                    '<a id="FFF-1"></a>',
                    "## [FFF-1] Support B",
                    "",
                    "Content. Balance rule follows [CCC-1](core.md#CCC-1).",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/nolayer.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: GGG",
                    "---",
                    "# No Layer",
                    "",
                    '<a id="GGG-1"></a>',
                    "## [GGG-1] No layer",
                    "",
                    "Content. Balance rule follows [CCC-1](core.md#CCC-1).",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["layers"])

        self.assertEqual(result.returncode, 0)
        supporting_line = next(
            (l for l in result.stdout.split("\n") if "supporting" in l and "core" in l), None
        )
        self.assertIsNotNone(supporting_line)
        self.assertRegex(supporting_line, r"\b2\b")
        no_layer_line = next(
            (
                l
                for l in result.stdout.split("\n")
                if re.search(r"(^|\s)-(\s|$)", l) and "core" in l
            ),
            None,
        )
        self.assertIsNotNone(no_layer_line)
        self.assertRegex(no_layer_line, r"\b1\b")

    def test_index_edge_from_is_set_only_for_references_inside_clause_body(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/a.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "layer: core",
                    "---",
                    "# A",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause A",
                    "",
                    "Content A.",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/05_specifications/b.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: DDD",
                    "layer: supporting",
                    "---",
                    "# B",
                    "",
                    '<a id="DDD-1"></a>',
                    "## [DDD-1] Clause B",
                    "",
                    "Content B. Balance rule follows [CCC-1](a.md#CCC-1).",
                    "",
                ]
            ),
        )
        write_file(
            root,
            "docs/03_design/notes.md",
            "\n".join(
                [
                    "# Notes",
                    "",
                    "| Clause | Description |",
                    "|---|---|",
                    "| [CCC-1](../05_specifications/a.md#CCC-1) | something |",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["index"])

        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)

        clause_edge = next((e for e in data["edges"] if e["fromFile"].endswith("b.md")), None)
        self.assertIsNotNone(clause_edge)
        self.assertEqual(clause_edge["from"], "DDD-1")

        consumer_edge = next(
            (e for e in data["edges"] if e["fromFile"].endswith("notes.md")), None
        )
        self.assertIsNotNone(consumer_edge)
        self.assertIsNone(consumer_edge["from"])


class SpecGraphAbbreviatedSectionReferenceTests(SpecGraphFixture):
    """V11's second pattern: an abbreviated reference is an identifier-shaped
    word (joined with _ or -, 2+ uppercase letters, or 2+ digits) or one of
    the project-configured document aliases (docs.docAliases in
    sprint.config.json), immediately followed by a section mark and a digit.
    An ordinary word before a section number, and a same-file bare section
    number, must not trigger it."""

    def test_v11_detects_abbreviated_section_number_reference(self):
        # Case A: a configured document alias (docs.docAliases) directly
        # followed by a section number. exit 1.
        lines_a = [
            "---",
            "xref-prefix: CCC",
            "---",
            "# Y",
            "",
            '<a id="CCC-1"></a>',
            "## [CCC-1] Clause",
            "",
            "The applicable rule is 運用指針 §1.3.",
            "",
        ]
        line_no_a = next(i for i, l in enumerate(lines_a) if "運用指針" in l and "§" in l) + 1
        root_a = self.mk_root()
        config_path = root_a / "sprint.config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["docs"]["docAliases"] = ["運用指針"]
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        write_file(root_a, "docs/05_specifications/y.md", "\n".join(lines_a))

        result_a = run_spec_graph(root_a, ["verify"])

        self.assertEqual(result_a.returncode, 1)
        self.assertIn("V11", result_a.stdout)
        self.assertIn(f"y.md:{line_no_a}", result_a.stdout)

        # Case B: an ASCII word directly followed by a section number.
        # exit 1.
        lines_b = [
            "---",
            "xref-prefix: CCC",
            "---",
            "# Y",
            "",
            '<a id="CCC-1"></a>',
            "## [CCC-1] Clause",
            "",
            "Refer to item_view §4.9 for details.",
            "",
        ]
        line_no_b = next(i for i, l in enumerate(lines_b) if "item_view" in l and "§" in l) + 1
        root_b = self.mk_root()
        write_file(root_b, "docs/05_specifications/y.md", "\n".join(lines_b))

        result_b = run_spec_graph(root_b, ["verify"])

        self.assertEqual(result_b.returncode, 1)
        self.assertIn("V11", result_b.stdout)
        self.assertIn(f"y.md:{line_no_b}", result_b.stdout)

        # Case C: a same-file section number with neither an ASCII word nor
        # a document alias immediately before it (a "(" breaks the
        # adjacency the pattern requires). exit 0.
        root_c = self.mk_root()
        write_file(
            root_c,
            "docs/05_specifications/y.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "---",
                    "# Y",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause",
                    "",
                    "See details at (§3) and (§6) below.",
                    "",
                ]
            ),
        )

        result_c = run_spec_graph(root_c, ["verify"])

        self.assertEqual(result_c.returncode, 0)

        # Case D: the same alias string, but only inside a code fence.
        # exit 0.
        root_d = self.mk_root()
        write_file(
            root_d,
            "docs/05_specifications/y.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "---",
                    "# Y",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause",
                    "",
                    "```",
                    "運用指針 §1.3",
                    "```",
                    "",
                ]
            ),
        )

        result_d = run_spec_graph(root_d, ["verify"])

        self.assertEqual(result_d.returncode, 0)

        # Case E: the first pattern (a `.md` filename within 8 characters
        # of a section mark) still works alongside the new second pattern.
        # exit 1.
        root_e = self.mk_root()
        write_file(
            root_e,
            "docs/05_specifications/y.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "---",
                    "# Y",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause",
                    "",
                    "The text references `foo.md` §3.2 for details.",
                    "",
                ]
            ),
        )

        result_e = run_spec_graph(root_e, ["verify"])

        self.assertEqual(result_e.returncode, 1)
        self.assertIn("V11", result_e.stdout)

        # Case F: an ordinary word directly before a section number. The
        # section number points at a section of the same file, in Japanese
        # and in English prose. exit 0.
        root_f = self.mk_root()
        write_file(
            root_f,
            "docs/05_specifications/y.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: CCC",
                    "---",
                    "# Y",
                    "",
                    '<a id="CCC-1"></a>',
                    "## [CCC-1] Clause",
                    "",
                    "Record the hash in §8 and read the §6 RETRO section.",
                    "本書 §6 と は §4.9 を読む。",
                    "",
                ]
            ),
        )

        result_f = run_spec_graph(root_f, ["verify"])

        self.assertEqual(result_f.returncode, 0)

        # Case G: the same string as Case A, with no alias configured. The
        # alias setting is what makes Case A fail. exit 0.
        root_g = self.mk_root()
        write_file(root_g, "docs/05_specifications/y.md", "\n".join(lines_a))

        result_g = run_spec_graph(root_g, ["verify"])

        self.assertEqual(result_g.returncode, 0)


class SpecGraphTestFileReferenceTests(SpecGraphFixture):
    """How spec-graph treats references made from test file names: only the
    [[ID]] inside a describe/it/test call's own name (never a comment, a
    fixture string literal, or link notation) counts, and the usual
    subcommands (index, verify, reverse, deps, files, diff) surface those
    references the same way they surface a document's."""

    def test_index_outputs_only_double_bracket_refs_in_test_name_lines_as_edges(self):
        root = self.mk_root()
        write_x_doc(root)

        a_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "// [[XX-1]] a mention inside a comment is not read as a reference",
            "describe('[[XX-1]] dummy description', () => {",
            "  it('[[XX-2]] dummy check', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/src/a.test.ts", "\n".join(a_lines))
        describe_line = a_lines.index("describe('[[XX-1]] dummy description', () => {") + 1
        it_line = a_lines.index("  it('[[XX-2]] dummy check', () => {") + 1
        comment_line = (
            a_lines.index("// [[XX-1]] a mention inside a comment is not read as a reference") + 1
        )

        b_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('[[XX-1]] frontend description', () => {",
            "  it('dummy check', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "frontend/src/b.test.tsx", "\n".join(b_lines))
        b_describe_line = b_lines.index("describe('[[XX-1]] frontend description', () => {") + 1

        c_lines = [
            "import { test, expect } from '@playwright/test'",
            "",
            "test('[[XX-2]] e2e dummy check', async ({ page }) => {",
            "  expect(1).toBe(1)",
            "})",
            "",
        ]
        write_file(root, "frontend/tests/e2e/c.spec.ts", "\n".join(c_lines))
        c_test_line = c_lines.index("test('[[XX-2]] e2e dummy check', async ({ page }) => {") + 1

        f_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('fixture check', () => {",
            "  it('a heading-like string is not read as a reference', () => {",
            "    const heading = '## [XX-1] Heading'",
            "    const inline = '[[XX-2]]'",
            "    expect(heading).toContain('[XX-1]')",
            "    expect(inline).toContain('XX-2')",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/src/scripts/f.test.ts", "\n".join(f_lines))

        nm_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('[[XX-1]] node_modules is not collected', () => {",
            "  it('dummy', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/node_modules/x/y.test.ts", "\n".join(nm_lines))

        result = run_spec_graph(root, ["index"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)

        a_edges = [e for e in data["edges"] if e["fromFile"] == "backend/src/a.test.ts"]
        self.assertEqual(
            a_edges,
            [
                {"from": None, "fromFile": "backend/src/a.test.ts", "line": describe_line, "to": "XX-1"},
                {"from": None, "fromFile": "backend/src/a.test.ts", "line": it_line, "to": "XX-2"},
            ],
        )
        self.assertFalse(any(e["line"] == comment_line for e in a_edges))

        b_edges = [e for e in data["edges"] if e["fromFile"] == "frontend/src/b.test.tsx"]
        self.assertEqual(
            b_edges,
            [{"from": None, "fromFile": "frontend/src/b.test.tsx", "line": b_describe_line, "to": "XX-1"}],
        )

        c_edges = [e for e in data["edges"] if e["fromFile"] == "frontend/tests/e2e/c.spec.ts"]
        self.assertEqual(
            c_edges,
            [
                {
                    "from": None,
                    "fromFile": "frontend/tests/e2e/c.spec.ts",
                    "line": c_test_line,
                    "to": "XX-2",
                }
            ],
        )

        f_edges = [e for e in data["edges"] if e["fromFile"] == "backend/src/scripts/f.test.ts"]
        self.assertEqual(f_edges, [])

        nm_edges = [e for e in data["edges"] if "node_modules" in e["fromFile"]]
        self.assertEqual(nm_edges, [])

    def test_index_reads_multiline_and_extended_call_forms_in_test_names(self):
        root = self.mk_root()
        write_x_doc(root)

        a_lines = [
            "import { describe, it, test, expect } from 'vitest'",
            "",
            "describe('multiline and extended call forms', () => {",
            "  it(",
            "    '[[XX-1]] a test name split across multiple lines',",
            "    () => {",
            "      expect(1).toBe(1)",
            "    },",
            "  )",
            "",
            "  test.describe('[[XX-2]] a playwright-style block', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "",
            "  it.each([1, 2])('[[XX-1]] a parametrized test %d', (n) => {",
            "    expect(n).toBeGreaterThan(0)",
            "  })",
            "",
            "  it('a comparison call', () => {",
            "    expect('[[XX-1]] this is an expect argument, not a reference').toContain('XX-1')",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/src/a.test.ts", "\n".join(a_lines))

        it_open_line = a_lines.index("  it(") + 1
        test_describe_line = (
            next(i for i, l in enumerate(a_lines) if l.startswith("  test.describe(")) + 1
        )
        it_each_line = next(i for i, l in enumerate(a_lines) if l.startswith("  it.each(")) + 1
        expect_arg_line = next(i for i, l in enumerate(a_lines) if "expect('[[XX-1]]" in l) + 1

        result = run_spec_graph(root, ["index"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        edges = [e for e in data["edges"] if e["fromFile"] == "backend/src/a.test.ts"]

        self.assertIn(
            {"from": None, "fromFile": "backend/src/a.test.ts", "line": it_open_line, "to": "XX-1"},
            edges,
        )
        self.assertIn(
            {
                "from": None,
                "fromFile": "backend/src/a.test.ts",
                "line": test_describe_line,
                "to": "XX-2",
            },
            edges,
        )
        self.assertIn(
            {"from": None, "fromFile": "backend/src/a.test.ts", "line": it_each_line, "to": "XX-1"},
            edges,
        )
        self.assertFalse(any(e["line"] == expect_arg_line for e in edges))

    def test_verify_detects_unknown_clause_in_test_name_via_v3_without_v8_v9_v11(self):
        root = self.mk_root()

        write_file(
            root,
            "docs/05_specifications/x.md",
            "\n".join(
                ["---", "xref-prefix: XX", "---", "# X", "", "## [XX-1] Clause 1", "", "Body 1.", ""]
            ),
        )

        a_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('mentioning SPEC §3.1 is not a section-number reference in a test', () => {",
            "  it('mentioning testing.md §8.1 is not a section-number reference in a test', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "",
            "  it('[XX-1](../docs/x.md#XX-1) link notation is not read as a reference', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "",
            "  it('[[XX-9]] references a clause that does not exist', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/src/a.test.ts", "\n".join(a_lines))
        missing_line = (
            a_lines.index("  it('[[XX-9]] references a clause that does not exist', () => {") + 1
        )

        result = run_spec_graph(root, ["verify"])

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"V3 参照先の条項が無い: backend/src/a.test.ts:{missing_line} XX-9", result.stdout
        )
        lines = result.stdout.split("\n")
        self.assertFalse(any(l.startswith("V11") for l in lines))
        self.assertFalse(any(l.startswith("V8") for l in lines))
        self.assertFalse(any(l.startswith("V9") for l in lines))

    def test_reverse_and_deps_output_test_files(self):
        root = self.mk_root()
        write_x_doc(root)

        a_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('[[XX-1]] a test', () => {",
            "  it('[[XX-2]] detail check', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/src/a.test.ts", "\n".join(a_lines))
        a_describe_line = a_lines.index("describe('[[XX-1]] a test', () => {") + 1

        c_lines = [
            "import { test, expect } from '@playwright/test'",
            "",
            "test('[[XX-1]] check via e2e', async ({ page }) => {",
            "  expect(1).toBe(1)",
            "})",
            "",
        ]
        write_file(root, "frontend/tests/e2e/c.spec.ts", "\n".join(c_lines))
        c_test_line = c_lines.index("test('[[XX-1]] check via e2e', async ({ page }) => {") + 1

        reverse_result = run_spec_graph(root, ["reverse", "XX-1"])
        self.assertEqual(reverse_result.returncode, 0)
        self.assertIn(f"backend/src/a.test.ts:{a_describe_line}", reverse_result.stdout)
        self.assertIn(f"frontend/tests/e2e/c.spec.ts:{c_test_line}", reverse_result.stdout)

        deps_result = run_spec_graph(root, ["deps", str(root / "backend/src/a.test.ts")])
        self.assertEqual(deps_result.returncode, 0)
        self.assertIn("XX-1", deps_result.stdout)
        self.assertIn("XX-2", deps_result.stdout)

    def test_files_refs_in_and_verify_refs_count_test_references(self):
        root = self.mk_root()
        write_x_doc(root)
        write_file(
            root,
            "docs/05_specifications/README.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: RULE",
                    "---",
                    "# README",
                    "",
                    "## [RULE-1] Reference",
                    "",
                    "A clause reference example is [[XX-1]].",
                    "",
                ]
            ),
        )

        a_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('[[XX-1]] a test', () => {",
            "  it('[[XX-2]] detail check', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/src/a.test.ts", "\n".join(a_lines))

        files_result = run_spec_graph(root, ["files"])
        self.assertEqual(files_result.returncode, 0)
        x_line = next(
            (l for l in files_result.stdout.split("\n") if l.startswith("docs/05_specifications/x.md")),
            None,
        )
        self.assertIsNotNone(x_line)
        self.assertRegex(x_line, r"refs-in=3\b")

        verify_result = run_spec_graph(root, ["verify"])
        self.assertEqual(verify_result.returncode, 0)
        m = re.search(r"verify: OK \((\d+) clauses, (\d+) refs, (\d+) files\)", verify_result.stdout)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(2)), 3)
        self.assertEqual(int(m.group(3)), 2)

    def test_diff_changed_shows_test_file_as_referrer(self):
        root = self.mk_root()
        write_x_doc(root)

        a_lines = [
            "import { describe, it, expect } from 'vitest'",
            "",
            "describe('[[XX-1]] a test', () => {",
            "  it('check', () => {",
            "    expect(1).toBe(1)",
            "  })",
            "})",
            "",
        ]
        write_file(root, "backend/src/a.test.ts", "\n".join(a_lines))
        a_describe_line = a_lines.index("describe('[[XX-1]] a test', () => {") + 1

        init = git(root, ["init", "-q"])
        self.assertEqual(init.returncode, 0)
        add = git(root, ["add", "-A"])
        self.assertEqual(add.returncode, 0)
        commit = git_commit(root, "initial")
        self.assertEqual(commit.returncode, 0)
        rev_parse = git(root, ["rev-parse", "HEAD"])
        self.assertEqual(rev_parse.returncode, 0)
        initial_ref = rev_parse.stdout.strip()

        write_file(
            root,
            "docs/05_specifications/x.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: XX",
                    "---",
                    "# X",
                    "",
                    "## [XX-1] Clause 1",
                    "",
                    "Body 1 (revised).",
                    "",
                    "## [XX-2] Clause 2",
                    "",
                    "Body 2.",
                    "",
                ]
            ),
        )

        result = run_spec_graph(root, ["diff", initial_ref])

        self.assertEqual(result.returncode, 0)
        self.assertIn("changed: XX-1", result.stdout)
        self.assertIn(f"    ← backend/src/a.test.ts:{a_describe_line}", result.stdout)


class SpecLintRefsTests(SpecGraphFixture):
    """harness/gate-tools/spec-lint.sh's `refs` check: the format of a
    sprint SPEC.md's "0. referenced common clauses" table. It accepts only
    the new link notation ([ID](path#ID)) or an explicit "no reference"
    marker row in the first column; the old [[ID]] notation and a table
    with no data row are both rejected, because spec-lint only ever reads
    one active sprint's SPEC.md (never a sealed historical one), so there
    is no reason left to keep accepting the old notation there."""

    def test_spec_refs_accepts_only_new_notation_and_no_reference_marker(self):
        root = self.mk_root()

        # (1) new notation: [XX-4](path#XX-4) -> exit 0
        new_notation_spec = write_file(
            root,
            "new-notation/SPEC.md",
            "\n".join(
                [
                    "# SPEC -- Fixture New Notation",
                    "",
                    "## 0. 参照する共通条項",
                    "",
                    "| 参照する条項 | 適用理由 | テストの扱い | Test ID / 理由 |",
                    "|---|---|---|---|",
                    "| [XX-4](../../../05_specifications/30_supporting/04_example.md#XX-4) "
                    "| applies a shared validation rule | 流用 | covered by the existing regression tests |",
                    "",
                    "---",
                    "",
                    "## 1. Body",
                    "",
                ]
            ),
        )

        # (2) the "no reference" marker row -> exit 0
        no_ref_spec = write_file(
            root,
            "no-ref/SPEC.md",
            "\n".join(
                [
                    "# SPEC -- Fixture No Reference",
                    "",
                    "## 0. 参照する共通条項",
                    "",
                    "| 参照する条項 | 適用理由 | テストの扱い | Test ID / 理由 |",
                    "|---|---|---|---|",
                    "| （参照なし） | — | 不要 | 共通条項に依存しない |",
                    "",
                    "---",
                    "",
                    "## 1. Body",
                    "",
                ]
            ),
        )

        # (3) positive case: only the old [[ID]] notation in column 1. The
        # other two columns are filled in correctly -- an empty column
        # would instead fail the empty-cell check, losing detection power
        # for the old notation itself. -> exit 1
        old_notation_spec = write_file(
            root,
            "old-notation/SPEC.md",
            "\n".join(
                [
                    "# SPEC -- Fixture Old Notation",
                    "",
                    "## 0. 参照する共通条項",
                    "",
                    "| 参照する条項 | 適用理由 | テストの扱い | Test ID / 理由 |",
                    "|---|---|---|---|",
                    "| [[XX-4]] | applies a shared validation rule | 流用 "
                    "| covered by the existing regression tests |",
                    "",
                    "---",
                    "",
                    "## 1. Body",
                    "",
                ]
            ),
        )

        # (4) positive case: header and separator rows only, no data row.
        # -> exit 1
        empty_table_spec = write_file(
            root,
            "empty-table/SPEC.md",
            "\n".join(
                [
                    "# SPEC -- Fixture Empty Table",
                    "",
                    "## 0. 参照する共通条項",
                    "",
                    "| 参照する条項 | 適用理由 | テストの扱い | Test ID / 理由 |",
                    "|---|---|---|---|",
                    "",
                    "---",
                    "",
                    "## 1. Body",
                    "",
                ]
            ),
        )

        result_new = run_spec_refs(new_notation_spec, root)
        result_no_ref = run_spec_refs(no_ref_spec, root)
        result_old = run_spec_refs(old_notation_spec, root)
        result_empty_table = run_spec_refs(empty_table_spec, root)

        # (1) and (2) are accepted.
        self.assertEqual(result_new.returncode, 0)
        self.assertEqual(result_no_ref.returncode, 0)

        # (3) a row with only the old notation fails.
        self.assertEqual(result_old.returncode, 1)
        # Confirm it fails *because* of the old notation, not because of
        # the empty-cell check: the empty-cell message must not appear,
        # and the "no reference-table row at all" message must.
        self.assertNotIn("「テストの扱い」が空である", result_old.stdout)
        self.assertNotIn("「Test ID / 理由」が空である", result_old.stdout)
        self.assertIn("§0 に条項参照の表行も（参照なし）行も無い", result_old.stdout)

        # (4) a table with no data row fails.
        self.assertEqual(result_empty_table.returncode, 1)


if __name__ == "__main__":
    unittest.main()
