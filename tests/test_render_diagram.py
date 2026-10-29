import importlib.util
import os
import time
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "plugins/render_diagram/render_diagram.py"
spec = importlib.util.spec_from_file_location("diagram_under_test", MODULE)
diagram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagram)
PNG = diagram.PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 200, 100)


class DiagramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def call(self, source="digraph { a -> b }", retain=False):
        return diagram.render_diagram(source, self.root, retain)

    def fake_render(self, args, **kwargs):
        self.assertIsInstance(args, list)
        self.assertNotIn("shell", kwargs)
        self.assertIn("--as=536870912", args)
        self.assertIn("--cpu=10", args)
        self.assertIn("--fsize=10000000", args)
        self.assertEqual(kwargs["timeout"], 15)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        Path(args[-1]).write_bytes(PNG)
        return subprocess.CompletedProcess(args, 0)

    def assert_clean(self):
        self.assertEqual(list((self.root / "diagrams").iterdir()), [])

    def test_default_success_removes_artifacts_and_returns_no_dead_path(self):
        with patch.object(diagram.shutil, "which", side_effect=lambda name: name), patch.object(
            diagram.subprocess, "run", side_effect=self.fake_render
        ):
            result = self.call()
        self.assertTrue(result.startswith("DIAGRAM_RENDERED:"), result)
        self.assertIn("removed", result)
        self.assertNotIn("file=", result)
        self.assert_clean()

    def test_explicit_retention_preserves_source_and_is_bounded(self):
        source = 'digraph { a [label="Meeting: 10:00"]; a -> b; }'
        with patch.object(diagram.shutil, "which", side_effect=lambda name: name), patch.object(
            diagram.subprocess, "run", side_effect=self.fake_render
        ), patch.object(diagram, "MAX_RETAINED_DIAGRAMS", 2):
            for _ in range(4):
                result = self.call(source, retain=True)
        self.assertIn("file=", result)
        self.assertIn("not sent", result)
        sources = list(self.root.rglob("*.dot"))
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].read_text(), source)

    def test_expired_artifacts_are_pruned_and_disabling_retention_removes_previous(self):
        with patch.object(diagram.shutil, "which", side_effect=lambda name: name), patch.object(
            diagram.subprocess, "run", side_effect=self.fake_render
        ):
            self.call(retain=True)
            old = next((self.root / "diagrams").iterdir())
            past = time.time() - diagram.MAX_ARTIFACT_AGE_SECONDS - 10
            os.utime(old, (past, past))
            self.call(retain=True)
            self.assertFalse(old.exists())
            self.call(retain="false")
        self.assert_clean()

    def test_pruning_leaves_unrelated_directory_alone(self):
        unrelated = self.root / "diagrams" / "keep-me"
        unrelated.mkdir(parents=True)
        with patch.object(diagram.shutil, "which", side_effect=lambda name: name), patch.object(
            diagram.subprocess, "run", side_effect=self.fake_render
        ):
            self.call()
        self.assertTrue(unrelated.exists())

    def test_cleanup_failure_is_reported_and_releases_lock(self):
        with patch.object(diagram.shutil, "which", side_effect=lambda name: name), patch.object(
            diagram.subprocess, "run", side_effect=self.fake_render
        ), patch.object(diagram.shutil, "rmtree", side_effect=PermissionError("denied")):
            self.assertIn("cleanup failed", self.call())
        self.assertFalse(diagram._RENDER_LOCK.locked())

    def test_invalid_input_including_surrogate_returns_failure(self):
        with patch.object(diagram.subprocess, "run") as run:
            for source in ("", "  ", None, "x" * 64001, "\ud800"):
                self.assertTrue(self.call(source).startswith("DIAGRAM_FAILED:"))
            run.assert_not_called()
        self.assert_clean()

    def test_missing_dot_or_resource_limiter_fails_closed(self):
        for missing in ("dot", "prlimit"):
            with patch.object(diagram.shutil, "which", side_effect=lambda name: None if name == missing else name):
                self.assertTrue(self.call().startswith("DIAGRAM_FAILED:"))
        self.assert_clean()

    def test_render_error_and_timeout_clean_up_even_with_retention(self):
        for outcome in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired("dot", 15)):
            kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
            with patch.object(diagram.shutil, "which", side_effect=lambda name: name), patch.object(
                diagram.subprocess, "run", **kwargs
            ):
                self.assertTrue(self.call(retain=True).startswith("DIAGRAM_FAILED:"))
            self.assert_clean()

    def test_invalid_or_oversized_dimensions_fail(self):
        for contents in (b"invalid", PNG[:16] + struct.pack(">II", 100000, 100)):
            def render(args, **kwargs):
                Path(args[-1]).write_bytes(contents)
                return subprocess.CompletedProcess(args, 0)
            with patch.object(diagram.shutil, "which", side_effect=lambda name: name), patch.object(
                diagram.subprocess, "run", side_effect=render
            ):
                self.assertTrue(self.call(retain=True).startswith("DIAGRAM_FAILED:"))
            self.assert_clean()

    def test_concurrent_render_is_rejected(self):
        with diagram._RENDER_LOCK:
            self.assertIn("another diagram", self.call())

    @unittest.skipUnless(shutil.which("dot") and shutil.which("prlimit"), "Linux Graphviz and prlimit required")
    def test_real_renderer(self):
        result = self.call(retain=True)
        self.assertTrue(result.startswith("DIAGRAM_RENDERED:"), result)
        self.assertGreater(next(self.root.rglob("*.png")).stat().st_size, 100)
        self.call()
        self.assert_clean()

    @unittest.skipUnless(shutil.which("dot") and shutil.which("prlimit"), "Linux Graphviz and prlimit required")
    def test_real_renderer_rejects_invalid_dot(self):
        self.assertTrue(self.call("digraph { a -> }").startswith("DIAGRAM_FAILED:"))
        self.assert_clean()

    @unittest.skipUnless(shutil.which("dot") and shutil.which("prlimit"), "Linux Graphviz and prlimit required")
    def test_real_renderer_bounds_huge_canvas(self):
        source = 'digraph { graph [dpi=100000]; a [width=100000,height=100000,fixedsize=true]; }'
        self.assertTrue(self.call(source).startswith("DIAGRAM_FAILED:"))
        self.assert_clean()
