"""Fixture-based tests for harness/tools/api-routes.sh.

api-routes.sh compares the set of API routes a project *implements* against
the set of routes its spec markdown *declares*, in both directions. The
implementation side is obtained by running an arbitrary shell command
(``API_ROUTES_IMPL_CMD``) that must print a JSON array of
``{"method": ..., "path": ...}`` objects; the spec side is scanned out of
``<API_ROUTES_ROOT>/<docs.specDir>/**/*.md`` (excluding README.md).

These tests exercise only the markdown-scanning / normalization / diff logic
of api-routes.sh itself, against synthetic spec markdown and a fake
implementation-route command (``cat`` of a small fixture JSON file, or a
trivial failing command). They do not spin up any real backend or run any
real route-dumping script.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "tools" / "api-routes.sh"


class ApiRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dirs = []

    def tearDown(self):
        for d in self.tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self.tmp_dirs = []

    # -- fixture helpers ---------------------------------------------------

    def mk_root(self):
        """Create a temp fixture root, pre-populated with a minimal
        sprint.config.json (schemaVersion 1, docs.specDir pointing at the
        same location writeSpec() writes into)."""
        root = tempfile.mkdtemp(prefix="csp-api-routes-")
        self.tmp_dirs.append(root)
        config = {
            "schemaVersion": 1,
            "docs": {"specDir": "docs/05_specifications"},
        }
        Path(root, "sprint.config.json").write_text(json.dumps(config))
        return root

    def write_spec(self, root, rel_path, content):
        """Write spec markdown under root/docs/05_specifications/<rel_path>."""
        file_path = Path(root, "docs", "05_specifications", rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return file_path

    def write_impl_routes(self, root, routes):
        """Write a fixture JSON array of {method, path} objects, mimicking
        the raw output of a real route-dumping script."""
        file_path = Path(root, "impl-routes.json")
        file_path.write_text(json.dumps(routes))
        return file_path

    def cat_cmd(self, file_path):
        return f"cat '{file_path}'"

    def empty_impl_cmd(self, root):
        return self.cat_cmd(self.write_impl_routes(root, []))

    def run_api_routes(self, root, args, impl_cmd):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = root
        env["API_ROUTES_ROOT"] = root
        env["API_ROUTES_IMPL_CMD"] = impl_cmd
        return subprocess.run(
            ["bash", str(SCRIPT_PATH), *args],
            env=env,
            capture_output=True,
            text=True,
        )

    def run_spec(self, root, impl_cmd):
        return self.run_api_routes(root, ["spec"], impl_cmd)

    def run_verify(self, root, impl_cmd):
        return self.run_api_routes(root, ["verify"], impl_cmd)

    def lines(self, stdout):
        return [l.strip() for l in stdout.split("\n") if l.strip() != ""]

    # -- declaration syntax: expand / alias / unknown word -----------------

    def test_expand_declaration_expands_placeholder_into_multiple_routes(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                [
                    "# Fixture",
                    "",
                    "```api-routes",
                    # comma-separated values, with deliberate surrounding
                    # whitespace, must be trimmed
                    "expand {resource} =  a ,  b  ",
                    "```",
                    "",
                    "GET /api/v1/{resource}",
                    "",
                ]
            ),
        )

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 0)
        self.assertEqual(sorted(self.lines(result.stdout)), ["GET /a", "GET /b"])

    def test_alias_declaration_maps_implementation_path_to_spec_path(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                [
                    "# Fixture",
                    "",
                    "```api-routes",
                    "alias GET /old -> /new",
                    "```",
                    "",
                    "GET /api/v1/new",
                    "",
                ]
            ),
        )
        impl_cmd = self.cat_cmd(
            self.write_impl_routes(root, [{"method": "GET", "path": "/api/v1/old"}])
        )

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 0)

    def test_unknown_declaration_word_exits_with_error_and_location(self):
        root = self.mk_root()
        file_path = self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                ["# Fixture", "", "```api-routes", "pending POST /x", "```", ""]
            ),
        )

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 1)
        self.assertIn("pending", result.stdout)
        basename = file_path.name
        self.assertRegex(result.stdout, rf"{basename}:\d+")

    # -- spec-side markdown scanning / normalization ------------------------

    def test_multiple_spaces_after_method_are_allowed(self):
        root = self.mk_root()
        self.write_spec(root, "fixture.md", "\n".join(["# Fixture", "", "GET    /api/v1/x", ""]))

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 0)
        self.assertIn("GET /x", self.lines(result.stdout))

    def test_backticks_and_optional_api_v1_prefix_are_normalized(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(["# Fixture", "", "`GET /api/v1/x`", "", "GET /x", ""]),
        )

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 0)
        out = self.lines(result.stdout)
        self.assertEqual(len([l for l in out if l == "GET /x"]), 1)

    def test_path_parameter_names_are_normalized_to_equivalent(self):
        root = self.mk_root()
        self.write_spec(root, "fixture.md", "\n".join(["# Fixture", "", "DELETE /api/v1/x/:id", ""]))
        impl_cmd = self.cat_cmd(
            self.write_impl_routes(root, [{"method": "DELETE", "path": "/api/v1/x/:someId"}])
        )

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 0)

    def test_wildcard_paths_are_excluded_from_spec_routes(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                [
                    "# Fixture",
                    "",
                    "GET /api/v1/masters/*",
                    "",
                    "GET /api/v1/masters/other",
                    "",
                ]
            ),
        )

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 0)
        out = self.lines(result.stdout)
        self.assertFalse(any("*" in l for l in out))
        self.assertIn("GET /masters/other", out)

    def test_mermaid_fence_contents_are_excluded_from_spec_routes(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                [
                    "# Fixture",
                    "",
                    "```mermaid",
                    "participant API as POST /api/v1/deliveries",
                    "```",
                    "",
                    "POST /api/v1/deliveries",
                    "",
                ]
            ),
        )

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 0)
        out = self.lines(result.stdout)
        # only the one occurrence outside the fence is counted (no double
        # counting of the one inside the mermaid fence)
        self.assertEqual(len([l for l in out if l == "POST /deliveries"]), 1)

    def test_trailing_punctuation_is_stripped_from_paths(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                [
                    "# Fixture",
                    "",
                    "Ends with a comma GET /api/v1/x, and a period GET /api/v1/x. here.",
                    "",
                ]
            ),
        )

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 0)
        out = self.lines(result.stdout)
        self.assertIn("GET /x", out)
        self.assertFalse(any("," in l for l in out))
        self.assertFalse(any(l.endswith(".") for l in out))

    def test_api_routes_fence_contents_are_excluded_from_spec_routes(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                ["# Fixture", "", "```api-routes", "alias GET /old -> /new", "```", ""]
            ),
        )

        result = self.run_spec(root, self.empty_impl_cmd(root))

        self.assertEqual(result.returncode, 0)
        out = self.lines(result.stdout)
        self.assertNotIn("GET /old", out)
        self.assertNotIn("GET /new", out)

    # -- verify: bidirectional diff and exit codes ---------------------------

    def test_verify_exits_zero_when_no_diff(self):
        root = self.mk_root()
        self.write_spec(root, "fixture.md", "\n".join(["# Fixture", "", "GET /api/v1/x", ""]))
        impl_cmd = self.cat_cmd(self.write_impl_routes(root, [{"method": "GET", "path": "/api/v1/x"}]))

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 0)

    def test_verify_exits_one_when_route_only_in_impl(self):
        root = self.mk_root()
        self.write_spec(root, "fixture.md", "\n".join(["# Fixture", "", "GET /api/v1/x", ""]))
        impl_cmd = self.cat_cmd(
            self.write_impl_routes(
                root,
                [
                    {"method": "GET", "path": "/api/v1/x"},
                    {"method": "GET", "path": "/api/v1/extra-only-in-impl"},
                ],
            )
        )

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 1)
        self.assertIn("実装にあって仕様に無い", result.stdout)
        self.assertIn("/extra-only-in-impl", result.stdout)

    def test_verify_exits_two_when_route_only_in_spec(self):
        root = self.mk_root()
        file_path = self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                ["# Fixture", "", "GET /api/v1/x", "", "GET /api/v1/extra-only-in-spec", ""]
            ),
        )
        impl_cmd = self.cat_cmd(self.write_impl_routes(root, [{"method": "GET", "path": "/api/v1/x"}]))

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 2)
        self.assertIn("/extra-only-in-spec", result.stdout)
        basename = file_path.name
        self.assertRegex(result.stdout, rf"{basename}:\d+")

    def test_verify_prefers_exit_one_when_diffs_in_both_directions(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                ["# Fixture", "", "GET /api/v1/x", "", "GET /api/v1/extra-only-in-spec", ""]
            ),
        )
        impl_cmd = self.cat_cmd(
            self.write_impl_routes(
                root,
                [
                    {"method": "GET", "path": "/api/v1/x"},
                    {"method": "GET", "path": "/api/v1/extra-only-in-impl"},
                ],
            )
        )

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 1)

    def test_verify_exits_one_when_impl_cmd_fails(self):
        root = self.mk_root()
        self.write_spec(root, "fixture.md", "\n".join(["# Fixture", "", "GET /api/v1/x", ""]))
        impl_cmd = "sh -c 'echo boom-from-impl-cmd >&2; exit 1'"

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 1)
        self.assertIn("boom-from-impl-cmd", result.stdout)
        # must not be treated as an empty implementation set: that would
        # collapse into a blanket "spec-only" diff instead of surfacing the
        # underlying command failure
        self.assertNotIn("仕様にあって実装に無い", result.stdout)

    def test_verify_exits_one_when_expand_declaration_is_unused(self):
        root = self.mk_root()
        # declares the {resource} placeholder but never uses it in the body
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                [
                    "# Fixture",
                    "",
                    "```api-routes",
                    "expand {resource} = a, b",
                    "```",
                    "",
                    "GET /api/v1/x",
                    "",
                ]
            ),
        )
        impl_cmd = self.cat_cmd(self.write_impl_routes(root, [{"method": "GET", "path": "/api/v1/x"}]))

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 1)

    def test_verify_exits_one_when_alias_declaration_is_unused(self):
        root = self.mk_root()
        self.write_spec(
            root,
            "fixture.md",
            "\n".join(
                ["# Fixture", "", "```api-routes", "alias GET /old -> /new", "```", "", "GET /api/v1/new", ""]
            ),
        )
        # implementation routes no longer contain /old (the compat route was
        # removed but the declaration was left behind)
        impl_cmd = self.cat_cmd(self.write_impl_routes(root, [{"method": "GET", "path": "/api/v1/new"}]))

        result = self.run_verify(root, impl_cmd)

        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
