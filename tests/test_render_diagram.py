import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "plugins/render_diagram/render_diagram.py"
spec = importlib.util.spec_from_file_location("diagram_under_test", MODULE)
diagram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagram)


class DiagramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def call(self, source):
        return diagram.render_diagram(source, self.root)

    def fake_render(self, args, **kwargs):
        self.assertIsInstance(args, list)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 15)
        self.assertEqual(kwargs["input"], self.source.encode("utf-8"))
        Path(args[-1]).write_bytes(diagram.PNG_SIGNATURE + b"fake-png")
        return subprocess.CompletedProcess(args, 0, stderr=b"")

    def test_preserves_source_and_returns_artifact_not_delivery_success(self):
        self.source = 'digraph { a [label="Meeting: 10:00"]; a -> b; }'
        with patch.object(diagram.shutil, "which", return_value="dot"), patch.object(
            diagram.subprocess, "run", side_effect=self.fake_render
        ):
            result = self.call(self.source)
            second = self.call(self.source)
        self.assertTrue(result.startswith("DIAGRAM_RENDERED:"), result)
        self.assertIn("not sent", result)
        self.assertNotEqual(result, second)
        sources = list(self.root.rglob("*.dot"))
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].read_text(encoding="utf-8"), self.source)

    def test_rejects_empty_and_oversized_source_without_starting_process(self):
        with patch.object(diagram.subprocess, "run") as run:
            for source in ("", "  ", None, "é" * 32001):
                self.assertTrue(self.call(source).startswith("DIAGRAM_FAILED:"))
            run.assert_not_called()

    def test_missing_renderer_has_actionable_error(self):
        with patch.object(diagram.shutil, "which", return_value=None):
            self.assertIn("install dot", self.call("digraph { a -> b }"))

    def test_syntax_error_is_reported_and_partial_files_removed(self):
        completed = subprocess.CompletedProcess([], 1, stderr=b"syntax error near '}'")
        with patch.object(diagram.shutil, "which", return_value="dot"), patch.object(
            diagram.subprocess, "run", return_value=completed
        ):
            self.assertIn("syntax error", self.call("digraph { a -> }"))
        self.assertEqual(list((self.root / "diagrams").iterdir()), [])

    def test_timeout_cleans_up(self):
        with patch.object(diagram.shutil, "which", return_value="dot"), patch.object(
            diagram.subprocess, "run", side_effect=subprocess.TimeoutExpired("dot", 15)
        ):
            self.assertIn("timeout", self.call("digraph { a -> b }"))
        self.assertEqual(list((self.root / "diagrams").iterdir()), [])

    def test_invalid_output_is_not_reported_as_success(self):
        def invalid(args, **kwargs):
            Path(args[-1]).write_bytes(b"not an image")
            return subprocess.CompletedProcess(args, 0, stderr=b"")
        with patch.object(diagram.shutil, "which", return_value="dot"), patch.object(
            diagram.subprocess, "run", side_effect=invalid
        ):
            self.assertIn("did not produce a PNG", self.call("digraph { a -> b }"))

    def test_output_limit(self):
        self.source = "digraph { a -> b }"
        with patch.object(diagram.shutil, "which", return_value="dot"), patch.object(
            diagram.subprocess, "run", side_effect=self.fake_render
        ), patch.object(diagram, "MAX_PNG_BYTES", 8):
            self.assertIn("exceeds", self.call(self.source))
        self.assertEqual(list((self.root / "diagrams").iterdir()), [])

    def test_unwritable_output_reports_failure(self):
        blocked = self.root / "file"
        blocked.write_text("not a directory")
        with patch.object(diagram.shutil, "which", return_value="dot"):
            self.assertTrue(
                diagram.render_diagram("digraph { a -> b }", blocked).startswith("DIAGRAM_FAILED:")
            )

    @unittest.skipUnless(shutil.which("dot"), "Graphviz dot is not installed")
    def test_real_renderer(self):
        result = self.call('digraph { a [label="Start 10:00"]; a -> b [label="yes"]; }')
        self.assertTrue(result.startswith("DIAGRAM_RENDERED:"), result)
        self.assertGreater(next(self.root.rglob("*.png")).stat().st_size, 100)

    @unittest.skipUnless(shutil.which("dot"), "Graphviz dot is not installed")
    def test_real_renderer_rejects_invalid_dot(self):
        self.assertTrue(self.call("digraph { a -> }").startswith("DIAGRAM_FAILED:"))


if __name__ == "__main__":
    unittest.main()
