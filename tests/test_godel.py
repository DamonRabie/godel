import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from godel.context import context
from godel.experiments import LOG_LIMIT, comparable, list_runs, run_experiment
from godel.history import append_event, list_history, provenance
from godel.projects import init_project, read_project
from godel.runtime import bundled_skills, launch_spec, local_environment
from godel.storage import Store, atomic_json


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="godel-test-")
        self.home = Path(self.temporary.name).resolve()
        shutil.copytree(REPO / "templates", self.home / "templates")
        self.root, self.project = init_project(self.home, "regression", "Predict a numeric target.")
        self.project.update(
            tags=["regression"],
            maxRunsPerSession=20,
            evaluation={
                "datasetId": "v1",
                "splitId": "fixed-v1",
                "metric": "mse",
                "direction": "minimize",
            },
        )
        atomic_json(self.root / "project.json", self.project)

    def tearDown(self):
        self.temporary.cleanup()

    def run_script(self, source, **changes):
        (self.root / "experiments/test.py").write_text(source)
        request = dict(
            hypothesis="Test a concrete behavior.",
            command=[sys.executable, "experiments/test.py"],
            sources=["experiments/test.py"],
            timeoutSeconds=5,
        )
        request.update(changes)
        return run_experiment(self.root, request, "test")

    def test_project_has_separate_git_and_python_structure(self):
        self.assertTrue((self.root / ".git").is_dir())
        self.assertTrue((self.root / "src/ml_project/__init__.py").is_file())
        self.assertEqual(read_project(self.root)["id"], self.project["id"])
        with self.assertRaises(ValueError):
            init_project(self.home, "regression")
        with self.assertRaises(ValueError):
            init_project(self.home, "../escape")

    def test_checkpoint_survives_new_store_and_updates_do_not_disappear(self):
        store = Store(self.home)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            entries = list(
                pool.map(
                    lambda n: store.checkpoint(
                        self.project["id"], f"Result {n}", "Next experiment", []
                    ),
                    range(8),
                )
            )
        self.assertIn(
            Store(self.home).latest_checkpoint(self.project["id"])["id"],
            {entry["id"] for entry in entries},
        )
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM checkpoints").fetchone()[0], 8)

    def test_context_refresh_discovers_integration_without_reading_secrets(self):
        self.assertFalse(context(self.home, self.root)["integrations"]["kaggle"]["configured"])
        for name in (
            "bin/kaggle.py",
            ".godel/tools/kaggle/bin/python",
            ".godel/kaggle/access_token",
        ):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private-test-secret")
        refreshed = context(self.home, self.root)
        self.assertTrue(refreshed["integrations"]["kaggle"]["configured"])
        self.assertNotIn("private-test-secret", json.dumps(refreshed))
        self.assertEqual(
            refreshed["integrations"]["kaggle"]["command"],
            ["python3", str(self.home / "bin/kaggle.py")],
        )

    def test_learning_lifecycle_and_project_boundaries(self):
        store = Store(self.home)
        lesson = store.propose(
            self.project["id"],
            "Use a group split.",
            "Run abc shows repeated users.",
            "project",
            ["regression"],
        )
        self.assertEqual(store.relevant(self.project, "split"), [])
        store.review(lesson["id"], "accept", "Reviewed the supporting run.")
        self.assertEqual(store.relevant(self.project, "split")[0]["id"], lesson["id"])
        other = dict(self.project, id=str(uuid.uuid4()))
        self.assertEqual(store.relevant(other, "split"), [])
        shared = store.propose(
            self.project["id"],
            "Compare with a mean baseline.",
            "Measured on synthetic v1.",
            "shared",
            ["regression"],
        )
        store.review(shared["id"], "accept", "Applicable to regression.")
        self.assertEqual(store.relevant(other, "baseline")[0]["id"], shared["id"])
        self.assertEqual(store.relevant(dict(other, tags=["vision"]), "baseline"), [])
        store.review(lesson["id"], "retire", "The task has changed.")
        self.assertNotIn(
            lesson["id"], [item["id"] for item in store.relevant(self.project, "split")]
        )
        self.assertEqual(store.relevant(self.project, "", max_chars=1), [])

    def test_history_is_immediate_complete_and_session_scoped(self):
        session_id = str(uuid.uuid4())
        append_event(
            self.root, session_id, "input", {"text": "Clarify the label horizon before training."}
        )
        # A reader can inspect the user prompt before any assistant message exists.
        listing = list_history(self.root)
        self.assertEqual(len(listing["sessions"]), 1)
        self.assertFalse((self.root / ".godel/history").exists())
        large_response = "measured output " * 30000
        append_event(self.root, session_id, "message_end", {"text": large_response})
        with Store(self.home).connection() as db:
            events = [
                json.loads(row[0])
                for row in db.execute("SELECT body FROM pending_history ORDER BY rowid")
            ]
        self.assertEqual(events[1]["data"]["text"], large_response)
        self.assertTrue(all(event["projectId"] == self.project["id"] for event in events))
        with self.assertRaises(ValueError):
            append_event(self.root, "../escape", "input", {})

    def test_history_concurrent_appends_preserve_json_records(self):
        session_id = str(uuid.uuid4())
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda n: append_event(self.root, session_id, "input", {"n": n}), range(12)
                )
            )
        with Store(self.home).connection() as db:
            values = {
                json.loads(row[0])["data"]["n"]
                for row in db.execute("SELECT body FROM pending_history")
            }
        self.assertEqual(values, set(range(12)))

    def test_real_experiment_and_evaluation_identity(self):
        source = (REPO / "examples/tiny_regression.py").read_text()
        record = self.run_script(source)
        self.assertEqual((record["status"], record["measurement"]), ("succeeded", "valid"))
        self.assertLess(record["metrics"]["mse"], record["metrics"]["baseline_mse"])
        run_dir = self.root / ".godel/runs" / record["id"]
        self.assertEqual((run_dir / "sources/experiments/test.py").read_text(), source)
        self.assertTrue((run_dir / "model.json").exists())
        self.assertTrue(comparable(record, self.project["evaluation"]))
        self.assertFalse(comparable(record, dict(self.project["evaluation"], splitId="other")))
        self.assertEqual(context(self.home, self.root)["bestMeasuredRun"]["id"], record["id"])

    def test_process_success_is_not_measurement_success(self):
        for body in ('{"mse": NaN}', '{"accuracy": 1}', '{"mse": true}'):
            with self.subTest(body=body):
                record = self.run_script(
                    "import os\nfrom pathlib import Path\n"
                    + f"(Path(os.environ['GODEL_RUN_DIR'])/'metrics.json').write_text({body!r})"
                )
                self.assertEqual(record["status"], "succeeded")
                self.assertEqual(record["measurement"], "invalid")
                self.assertFalse(comparable(record, self.project["evaluation"]))
        missing = self.run_script("print('done')")
        self.assertEqual(missing["measurement"], "missing")
        failed = self.run_script(
            (REPO / "examples/tiny_regression.py").read_text() + "\nraise SystemExit(3)\n"
        )
        self.assertEqual(failed["measurement"], "valid")
        self.assertFalse(comparable(failed, self.project["evaluation"]))
        self.assertIsNone(context(self.home, self.root)["bestMeasuredRun"])

    def test_timeout_and_output_limit(self):
        record = self.run_script("import time\ntime.sleep(30)", timeoutSeconds=1)
        self.assertEqual(record["status"], "timed_out")
        self.assertLess(record["durationSeconds"], 4)
        record = self.run_script("print('x' * 3000000)")
        self.assertTrue(record["logTruncated"])
        self.assertEqual(
            (self.root / ".godel/runs" / record["id"] / "output.log").stat().st_size, LOG_LIMIT
        )

    def test_budget_and_source_path_checks(self):
        with self.assertRaises(ValueError):
            self.run_script("pass", timeoutSeconds=301)
        self.project["maxRunsPerSession"] = 1
        atomic_json(self.root / "project.json", self.project)
        record = self.run_script("pass", sources=["../outside.py"])
        self.assertEqual(record["status"], "failed")
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.run_script("pass")

    def test_symlink_source_cannot_escape_project(self):
        outside = self.home / "outside.py"
        outside.write_text("secret = 1")
        (self.root / "escape.py").symlink_to(outside)
        record = self.run_script("pass", sources=["escape.py"])
        self.assertEqual(record["status"], "failed")
        self.assertNotIn("pid", record)

    def test_provider_credentials_and_shell_hooks_are_not_inherited(self):
        env = local_environment(
            {
                "PATH": "/bin",
                "HOME": "/home/user",
                "OPENAI_API_KEY": "test-secret",
                "PI_CODING_AGENT_DIR": "/global",
                "BASH_ENV": "/global/hook",
            }
        )
        self.assertEqual(env, {"PATH": "/bin", "HOME": "/home/user"})
        (self.home / "node_modules/.bin").mkdir(parents=True)
        (self.home / "node_modules/.bin/pi").touch()
        (self.home / "dist/pi").mkdir(parents=True)
        (self.home / "dist/pi/extension.js").touch()
        (self.home / "agent/prompts").mkdir(parents=True)
        shutil.copytree(REPO / "agent/skills", self.home / "agent/skills")
        command, env = launch_spec(self.home, self.root)
        self.assertEqual(env["PI_CODING_AGENT_DIR"], str(self.home / ".godel/pi"))
        for flag in (
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
        ):
            self.assertIn(flag, command)
        self.assertEqual(
            command[command.index("--session-dir") + 1], str(self.root / ".godel/sessions")
        )
        explicit_skills = [command[i + 1] for i, arg in enumerate(command) if arg == "--skill"]
        self.assertEqual(explicit_skills, [str(path) for path in bundled_skills(self.home)])
        self.assertEqual(len(explicit_skills), 4)

    def test_skills_cannot_resolve_outside_the_bundle(self):
        outside = self.home / "outside/SKILL.md"
        outside.parent.mkdir()
        outside.write_text("Unwanted external skill")
        skill = self.home / "agent/skills/escape/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "inside agent/skills"):
            bundled_skills(self.home)

    def test_provenance_tracks_skill_and_reference_edits(self):
        shutil.copytree(REPO / "agent/skills", self.home / "agent/skills")
        before = provenance(self.home)
        reference = "agent/skills/ml-validation/references/target-encoding.md"
        entrypoint = "agent/skills/ml-validation/SKILL.md"
        self.assertIn(entrypoint, before)
        (self.home / reference).write_text("Updated encoding guidance")
        after = provenance(self.home)
        self.assertNotEqual(before[reference], after[reference])
        self.assertEqual(before[entrypoint], after[entrypoint])
        script = "agent/skills/ml-diagnostics/scripts/summarize_errors.py"
        self.assertIn(script, before)
        (self.home / script).write_text("# updated helper")
        self.assertNotEqual(before[script], provenance(self.home)[script])

    def test_cancellation_records_outcome_and_stops_child(self):
        (self.root / "experiments/wait.py").write_text("import time\ntime.sleep(30)")
        payload = dict(
            request=dict(
                hypothesis="Cancellation test",
                command=[sys.executable, "experiments/wait.py"],
                sources=["experiments/wait.py"],
                timeoutSeconds=30,
            ),
            sessionId="cancel",
        )
        script = (
            "import sys,json; from godel.experiments import run_experiment; "
            "p=json.loads(sys.argv[2]); print(json.dumps(run_experiment(sys.argv[1],p['request'],p['sessionId'])))"
        )
        env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
        proc = subprocess.Popen(
            [sys.executable, "-c", script, str(self.root), json.dumps(payload)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                records = list_runs(self.root)
                if records and "pid" in records[0]:
                    break
                time.sleep(0.05)
            else:
                self.fail("Experiment did not start.")
            proc.send_signal(signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, stderr)
            record = json.loads(stdout)
            self.assertEqual(record["status"], "cancelled")
            with self.assertRaises(ProcessLookupError):
                os.kill(record["pid"], 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


if __name__ == "__main__":
    unittest.main()
