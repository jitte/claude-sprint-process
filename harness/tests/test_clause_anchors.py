"""Tests for harness/tools/clause-anchors.sh / clause-anchors.py.

Ported from the original TypeScript/vitest test suite to Python 3 standard
library only (unittest + tempfile + subprocess), so the harness's own
regression tests can run with just python3/bash/jq/git installed.

The tool inserts an explicit ``<a id="ID"></a>`` anchor immediately before
each declared condition heading (``## [ID] ...``) in a "clause file" (a
living-docs markdown file whose frontmatter declares ``xref-prefix``), and
rewrites ``[[ID]]`` double-bracket references elsewhere into markdown links
(``[ID](path#ID)``). See docs/05_specifications/README.md (the RULE-1
section) for the anchor/reference convention this implements.

The fixture corpus is built from scratch in a temporary directory for every
test and does not depend on any file from the project this harness was
copied out of. The scan root is swapped in via the ``CLAUSE_ANCHORS_ROOT``
environment variable that clause-anchors.sh reads.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# Repository root: two levels above this file (harness/tests/test_clause_anchors.py
# -> harness/tests -> harness -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]

SCRIPT_PATH = REPO_ROOT / "harness" / "tools" / "clause-anchors.sh"


def write_sprint_config(root: Path) -> None:
    """Minimal sprint.config.json placed directly under the fixture root.

    clause-anchors.py reads docs.livingDirs and docs.templates from the
    config found at the scan root (harness/lib/config.py's load()). The
    living-docs layout mirrors the one documented for this harness.
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
        "components": {},
        "evidence": {"dir": ".sprint/test-result"},
        "sets": {},
        "gateToolsDirs": [],
        "gates": {},
    }
    import json

    root.mkdir(parents=True, exist_ok=True)
    (root / "sprint.config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")


def write_file(root: Path, rel_path: str, content: str) -> Path:
    """Write a file under root, creating parent directories as needed."""
    file_path = root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def read_file(root: Path, rel_path: str) -> str:
    return (root / rel_path).read_text(encoding="utf-8")


def run_clause_anchors(root: Path, args=None):
    """Run clause-anchors.sh as a subprocess against the fixture root."""
    env = dict(os.environ)
    env["CLAUSE_ANCHORS_ROOT"] = str(root)
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *(args or [])],
        env=env,
        capture_output=True,
        text=True,
    )


class ClauseAnchorsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="csp-clause-anchors-")).resolve()
        write_sprint_config(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_xref_prefix_declaration_determines_anchor_and_reference_targets(self):
        # Clause file (declares xref-prefix): an anchor is inserted right
        # before the declared heading.
        write_file(
            self.root,
            "docs/04_standards/x.md",
            "\n".join(
                [
                    "---",
                    "xref-prefix: RULE",
                    "---",
                    "# X",
                    "",
                    "## [RULE-1] Heading",
                    "",
                    "THE system SHALL follow something.",
                    "",
                ]
            ),
        )
        # Living-docs consumer file: [[RULE-1]] is rewritten into a link.
        write_file(
            self.root,
            "docs/90_deliverables/y.md",
            "\n".join(["# Y", "", "The reference follows [[RULE-1]].", ""]),
        )
        # Under the templates directory: [[RULE-1]] is left untouched.
        write_file(
            self.root,
            "docs/06_process/templates/z.md",
            "\n".join(["# Z Template", "", "The reference follows [[RULE-1]].", ""]),
        )

        result = run_clause_anchors(self.root)

        self.assertEqual(result.returncode, 0)

        x_content = read_file(self.root, "docs/04_standards/x.md")
        self.assertIn('<a id="RULE-1"></a>\n## [RULE-1] Heading', x_content)

        y_content = read_file(self.root, "docs/90_deliverables/y.md")
        self.assertIn("[RULE-1](../04_standards/x.md#RULE-1)", y_content)
        self.assertNotIn("[[RULE-1]]", y_content)

        z_content = read_file(self.root, "docs/06_process/templates/z.md")
        self.assertIn("[[RULE-1]]", z_content)


if __name__ == "__main__":
    unittest.main()
