"""Tests for harness/gate-tools/doc-verified.sh: the docs-sprint gate reads
the verdict table inside TEST.md's UNSEAL block (the first table whose
header row has a 判定 column) and passes only when the latest filled-in
round's verdict cell is exactly 🟢.

It must look at table cells only: 🔴 / 🟢 appearing in prose inside the
UNSEAL block must not change the result (that mis-detection stopped a SHIP
in the project this harness was copied out of).

Python 3 standard library only. Fixtures are built in a temporary directory
and the gate is pointed at them with CLAUDE_PROJECT_DIR.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_VERIFIED_SH = REPO_ROOT / "harness" / "gate-tools" / "doc-verified.sh"

SPRINT_DIR = "docs/07_plans/01_x/01_x"


def write_file(root: Path, rel_path: str, lines) -> None:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_project(root: Path) -> None:
    write_file(root, "sprint.config.json", [json.dumps({
        "schemaVersion": 1,
        "project": {"name": "fixture"},
        "docs": {"sprintRoot": "docs/07_plans"},
    })])
    write_file(root, ".sprint/flags.json", [json.dumps({
        "active": "1-1",
        "sprints": {"1-1": {"stage": "TEST", "status": "open", "sprint_dir": SPRINT_DIR, "kind": "docs"}},
    })])


def test_md(rounds, prose=None):
    """UNSEAL block with the template's verdict table. `rounds` is a list of
    (round, date, verdict, result) rows; `prose` is extra lines placed inside
    the UNSEAL block after the table."""
    lines = ["# TEST", "", "本文（封印領域）。🔴 は封印領域にあっても無視される。", "",
             "<!-- UNSEAL:BEGIN -->", "",
             "| 巡 | 実施日 | 判定 | 結果 |", "|---|---|---|---|"]
    for r in rounds:
        lines.append("| %s | %s | %s | %s |" % r)
    lines += ["", "### 静的検証の実測", "", "| ID | 記入者 | 実測 | 判定 |", "|----|--------|------|------|",
              "| S-1 | qa | — | 🔴 |"]
    if prose:
        lines += [""] + list(prose)
    lines += ["", "<!-- UNSEAL:END -->"]
    return lines


def run_gate(root: Path):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    for key in ("SPRINT_CONFIG", "SPRINT_GATE"):
        env.pop(key, None)
    return subprocess.run(["bash", str(DOC_VERIFIED_SH)], cwd=str(root), env=env,
                          capture_output=True, text=True)


class DocVerifiedTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="csp-doc-verified-")).resolve()
        write_project(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_latest_round_green_passes_even_with_red_in_prose(self):
        write_file(self.root, SPRINT_DIR + "/TEST.md", test_md(
            [("1", "2026-09-01", "🔴", "不整合 2 件"), ("2", "2026-09-02", "🟢", "解消")],
            prose=["### 検査していない観点", "", "- 1 巡目の 🔴 は 2 巡目で解消した。"]))
        r = run_gate(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok: TEST.md 整合性チェック green（最新の巡）", r.stdout)

    def test_latest_round_red_fails(self):
        write_file(self.root, SPRINT_DIR + "/TEST.md", test_md(
            [("1", "2026-09-01", "🟢", "ok"), ("2", "2026-09-02", "🔴", "再発")]))
        r = run_gate(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("最新の巡の判定が 🔴", r.stdout)

    def test_template_placeholder_row_counts_as_unfilled(self):
        write_file(self.root, SPRINT_DIR + "/TEST.md", test_md([("—", "—", "🔴🟡🟢", "—")]))
        r = run_gate(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("判定が記入された行がない", r.stdout)

    def test_green_in_prose_only_does_not_pass(self):
        write_file(self.root, SPRINT_DIR + "/TEST.md", test_md(
            [("—", "—", "🔴🟡🟢", "—")], prose=["すべて 🟢 だった。"]))
        r = run_gate(self.root)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
