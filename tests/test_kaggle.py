"""Credential boundary and optional installed Kaggle CLI compatibility."""

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class KaggleTests(unittest.TestCase):
    def test_credentials_stay_in_child_environment_and_output_is_redacted(self):
        spec = importlib.util.spec_from_file_location("godel_kaggle", ROOT / "bin/kaggle.py")
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            token = home / ".godel/kaggle/access_token"
            token.parent.mkdir(parents=True)
            token.write_text("test-secret\n")
            python = home / ".godel/tools/kaggle/bin/python"
            python.parent.mkdir(parents=True)
            python.touch()
            wrapper.__file__ = str(home / "bin/kaggle.py")
            out, err = io.StringIO(), io.StringIO()
            with (
                patch.object(wrapper.subprocess, "run") as run,
                patch.dict(wrapper.os.environ, {"KAGGLE_USERNAME": "unrelated"}),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                run.return_value = subprocess.CompletedProcess(
                    [],
                    7,
                    b"test-secret",
                    b"test-secret https://storage.googleapis.com/file?Signature=secret",
                )
                self.assertEqual(wrapper.main(), 7)
            self.assertEqual(out.getvalue(), "[REDACTED]")
            self.assertEqual(
                err.getvalue(), "[REDACTED] https://storage.googleapis.com/file?[REDACTED]"
            )
            self.assertNotIn("test-secret", str(run.call_args.args))
            self.assertIn("-I", run.call_args.args[0])
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["KAGGLE_API_TOKEN"], "test-secret")
            self.assertNotIn("KAGGLE_USERNAME", env)

    @unittest.skipUnless(
        (ROOT / ".godel/tools/kaggle/bin/python").exists(), "Optional Kaggle CLI is not installed"
    )
    def test_installed_cli_route_and_imports(self):
        code = (
            "from kaggle.cli import main; "
            "from kagglesdk.kaggle_env import get_endpoint, KaggleEnv; "
            "from importlib.metadata import version; "
            "assert version('kaggle') == '2.2.4'; "
            "assert version('kagglesdk') == '0.1.37'; "
            "assert get_endpoint(KaggleEnv.PROD) == 'https://api.kaggle.com'"
        )
        result = subprocess.run(
            [str(ROOT / ".godel/tools/kaggle/bin/python"), "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
