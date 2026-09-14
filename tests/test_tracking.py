"""Persistence contracts plus an opt-in real local MLflow integration check."""

import hashlib
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from godel.cli import api
from godel.experiments import list_runs, run_experiment
from godel.history import append_event, import_history
from godel.projects import init_project
from godel.records import evidence, get_run, query_history, save_run
from godel.review import review_experiment
from godel.runtime import local_environment
from godel.remote import remote_run
from godel.storage import Store, atomic_json
from godel.tracking import Client, start, stop, status, sync


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="godel-tracking-")
        self.home = Path(self.temp.name).resolve()
        shutil.copytree(REPO / "templates", self.home / "templates")
        self.root, self.project = init_project(self.home, "example", "Track a test experiment.")
        self.project["evaluation"] = dict(
            datasetId="test-v1", splitId="fixed", metric="mse", direction="minimize"
        )
        self.project["maxRunsPerSession"] = 20
        atomic_json(self.root / "project.json", self.project)
        self.session = str(uuid.uuid4())
        self.store = Store(self.home)

    def tearDown(self):
        self.temp.cleanup()

    def run_example(self, failed=False):
        source = (REPO / "examples/tiny_regression.py").read_text()
        source += '\n(run_dir / "metric-history.json").write_text(json.dumps([{"step": 1, "metrics": {"train_loss": 2.0, "mse": 99.0}}, {"step": 2, "metrics": {"train_loss": 1.0, "mse": 88.0}}]))\n'
        if failed:
            source += "raise SystemExit(3)\n"
        (self.root / "experiments/baseline.py").write_text(source)
        return run_experiment(
            self.root,
            dict(
                hypothesis="A line fits this data.",
                command=[sys.executable, "experiments/baseline.py"],
                sources=["experiments/baseline.py"],
                timeoutSeconds=5,
                parameters={"seed": 17, "fit_intercept": True},
            ),
            self.session,
            tool_call_id="tool-1",
        )

    def remote_example(self):
        (self.root / "remote.py").write_text("# submitted code\n")
        request = dict(
            action="register",
            hypothesis="Remote fixture",
            candidateCount=1,
            sources=["remote.py"],
            remote=dict(platform="kaggle", jobId="fixture/test", version="11"),
        )
        run = remote_run(self.root, request, self.session)
        (self.root / "download.log").write_text("version 11 completed; mse=0.25\n")
        atomic_json(self.root / "download.json", {"mse": 0.25})
        finish = dict(
            action="finish",
            runId=run["id"],
            remote=request["remote"],
            status="succeeded",
            provenance="Fixture version 11 completion evidence in output.log",
            files={"output.log": "download.log", "metrics.json": "download.json"},
        )
        return request, run, finish

    def test_remote_offline_lifecycle_idempotency_and_conflicts(self):
        request, run, finish = self.remote_example()
        self.assertEqual(remote_run(self.root, request, "resumed")["id"], run["id"])
        self.assertEqual(len(list_runs(self.root)), 1)
        completed = remote_run(self.root, finish, "resumed")
        self.assertEqual(completed["measurement"], "valid")
        self.assertEqual(completed["sessionId"], self.session)
        self.assertEqual(remote_run(self.root, finish), completed)
        self.assertEqual(status(self.home)["pending"], 1)
        atomic_json(self.root / "download.json", {"mse": 9})
        with self.assertRaisesRegex(ValueError, "immutable"):
            remote_run(self.root, finish)
        with self.assertRaisesRegex(ValueError, "different metadata"):
            remote_run(self.root, {**request, "hypothesis": "changed"})

    def test_remote_rejects_wrong_version_paths_and_missing_provenance(self):
        _, run, finish = self.remote_example()
        for changes in (
            {"remote": {**finish["remote"], "version": "12"}},
            {"files": {"output.log": "../outside"}},
            {"files": {"output.log": "download.log", "run.json": "download.json"}},
            {"status": "running"},
            {"provenance": ""},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                remote_run(self.root, {**finish, **changes})
        (self.root / "linked.log").symlink_to(self.root / "download.log")
        with self.assertRaisesRegex(ValueError, "symlink"):
            remote_run(self.root, {**finish, "files": {"output.log": "linked.log"}})
        self.assertEqual(get_run(self.root, run["id"])["status"], "running")

    def test_remote_failure_missing_and_invalid_metrics_and_budget(self):
        request, run, finish = self.remote_example()
        self.project["maxRunsPerSession"] = 1
        atomic_json(self.root / "project.json", self.project)
        with self.assertRaisesRegex(ValueError, "budget"):
            remote_run(
                self.root,
                {**request, "remote": {**request["remote"], "version": "12"}},
                self.session,
            )
        self.assertEqual(
            remote_run(
                self.root, {**finish, "status": "failed", "files": {"output.log": "download.log"}}
            )["measurement"],
            "missing",
        )
        for terminal in ("cancelled", "timed_out", "succeeded"):
            other = remote_run(
                self.root,
                {**request, "remote": {**request["remote"], "version": terminal}},
                terminal,
            )
            atomic_json(self.root / "download.json", {"wrong_metric": 1})
            result = remote_run(
                self.root,
                {**finish, "runId": other["id"], "remote": other["remote"], "status": terminal},
            )
            self.assertEqual(result["measurement"], "invalid")
            self.assertEqual(result["status"], terminal)

    def test_remote_import_resume_and_api_keep_frozen_evaluation(self):
        request, run, finish = self.remote_example()
        with patch("godel.remote.collect_results", side_effect=OSError("interrupted import")):
            with self.assertRaises(OSError):
                remote_run(self.root, finish)
        self.assertEqual(get_run(self.root, run["id"])["status"], "running")
        with self.assertRaisesRegex(ValueError, "original result bundle"):
            remote_run(self.root, {**finish, "provenance": "changed bundle"})
        self.project["evaluation"]["metric"] = "new_metric"
        atomic_json(self.root / "project.json", self.project)
        result = api(
            self.home, self.root, "remote_run", {"request": finish, "sessionId": "resumed"}
        )
        self.assertEqual(result["evaluation"]["metric"], "mse")
        self.assertEqual(result["measurement"], "valid")
        self.assertEqual(result["sessionId"], self.session)

    def test_v1_migration_preserves_lessons_and_checkpoints_and_rejects_future_schema(self):
        path = self.home / "old/.godel/state.sqlite3"
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as db:
            db.executescript(
                "CREATE TABLE checkpoints(sequence INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, body TEXT NOT NULL); "
                "CREATE TABLE lessons(id TEXT PRIMARY KEY, body TEXT NOT NULL); PRAGMA user_version=1;"
            )
            db.execute(
                "INSERT INTO checkpoints(project_id,body) VALUES (?,?)",
                (self.project["id"], '{"summary":"retained"}'),
            )
            db.execute("INSERT INTO lessons VALUES (?,?)", ("old", '{"lesson":"retained"}'))
        migrated = Store(self.home / "old")
        self.assertEqual(migrated.latest_checkpoint(self.project["id"])["summary"], "retained")
        self.assertEqual(migrated.lessons()[0]["lesson"], "retained")
        with migrated.connection() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            Store(self.home / "old")

    def test_events_survive_missing_journal_and_pagination_is_project_scoped(self):
        for n in range(5):
            append_event(self.root, self.session, "input", {"text": f"baseline {n}"})
        path = self.root / ".godel/history" / f"{self.session}.jsonl"
        self.assertFalse(path.exists())
        first = query_history(self.store, self.project["id"], query="baseline", limit=2)
        second = query_history(self.store, self.project["id"], after=first["nextCursor"], limit=2)
        self.assertEqual(
            [e["data"]["text"] for e in second["events"]], ["baseline 2", "baseline 3"]
        )
        self.assertEqual(query_history(self.store, str(uuid.uuid4()))["events"], [])
        with self.assertRaises(ValueError):
            query_history(self.store, self.project["id"], limit=10000)

    def test_legacy_import_is_idempotent_and_preserves_corrupt_tail(self):
        run = self.run_example()
        append_event(self.root, self.session, "input", {"text": "legacy"})
        path = self.root / ".godel/history" / f"{self.session}.jsonl"
        path.parent.mkdir(parents=True)
        with self.store.connection() as db:
            body = db.execute("SELECT body FROM pending_history").fetchone()[0]
        path.write_text(body + "\n" + '{"interrupted":')
        original = path.read_bytes()
        with self.store.connection() as db:
            db.execute("DELETE FROM evidence_links")
            db.execute("DELETE FROM outbox")
            db.execute("DELETE FROM runs")
            db.execute("DELETE FROM events")
            db.execute("DELETE FROM pending_history")
            db.execute("DELETE FROM history_refs")
        imported = import_history(self.home)
        self.assertEqual(imported["eventsImported"], 1)
        self.assertEqual(imported["runsIndexed"], 1)
        self.assertEqual(len(imported["warnings"]), 1)
        self.assertEqual(import_history(self.home)["eventsImported"], 0)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list_runs(self.root)[0]["id"], run["id"])

    def test_run_decision_lesson_and_reuse_links_are_traversable(self):
        run = self.run_example()
        refs = [{"type": "run", "id": run["id"]}]
        decision = api(
            self.home,
            self.root,
            "decision",
            dict(
                sessionId=self.session,
                summary="Keep linear baseline",
                rationale="It beats the mean.",
                evidenceRefs=refs,
            ),
        )
        lesson = self.store.propose(
            self.project["id"],
            "Try a linear baseline.",
            "Measured improvement.",
            evidence_refs=[{"type": "event", "id": decision["eventId"]}],
            session_id=self.session,
        )
        self.store.review(lesson["id"], "accept", "Reviewed")
        append_event(self.root, self.session, "context", {"context": {"lessons": [lesson]}})
        graph = evidence(self.store, self.project["id"], run["id"])
        self.assertTrue(any(link["sourceId"] == decision["eventId"] for link in graph["links"]))
        self.assertTrue(any(link["targetId"] == "tool-1" for link in graph["links"]))
        self.assertEqual(
            evidence(self.store, self.project["id"], lesson["id"])["lesson"]["status"], "active"
        )
        self.assertTrue(evidence(self.store, self.project["id"], lesson["id"])["events"])
        with self.assertRaisesRegex(ValueError, "this project"):
            self.store.propose(str(uuid.uuid4()), "Wrong", "Wrong project", evidence_refs=refs)

    def test_queue_survives_outage_and_new_revision_during_export(self):
        run = self.run_example()
        self.assertEqual(status(self.home)["pending"], 1)
        with patch.object(Client, "request", side_effect=ConnectionRefusedError("offline")):
            self.assertEqual(sync(self.home, force=True)["synced"], 0)
        self.assertEqual(status(self.home)["runs"][0]["attempts"], 1)
        self.assertEqual(list_runs(self.root)[0]["status"], "succeeded")
        with self.store.connection() as db:
            revision = db.execute("SELECT revision FROM outbox").fetchone()[0]
        changed = dict(run, extra="new local evidence")
        save_run(self.root, changed)
        with self.store.connection() as db:
            db.execute("UPDATE outbox SET synced_revision=?", (revision,))
        self.assertEqual(status(self.home)["pending"], 1)
        save_run(self.root, changed)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT revision FROM outbox").fetchone()[0], revision + 1)

    def test_run_metadata_is_available_without_run_json(self):
        run = self.run_example()
        (self.root / ".godel/runs" / run["id"] / "run.json").unlink()
        self.assertEqual(list_runs(self.root)[0]["id"], run["id"])
        self.assertEqual(list_runs(self.root)[0]["metricHistory"][1]["metrics"]["train_loss"], 1.0)
        self.assertEqual(review_experiment(self.root, run["id"])["runId"], run["id"])

    @unittest.skipUnless(
        os.environ.get("GODEL_TEST_MLFLOW") == "1",
        "run make verify-tracking for a real local server",
    )
    def test_service_can_stop_and_immediately_restart(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        atomic_json(self.home / ".godel/tracking.json", {"port": port})
        (self.home / ".venv").symlink_to(REPO / ".venv", target_is_directory=True)
        (self.home / "bin").mkdir()
        # A temporary entrypoint keeps this lifecycle check's state out of the
        # real workspace while invoking the actual service implementation.
        (self.home / "bin/godel.py").write_text(
            f"import sys\nfrom pathlib import Path\nsys.path.insert(0, {str(REPO / 'src')!r})\n"
            "from godel.tracking import serve\nserve(Path(__file__).resolve().parents[1])\n"
        )
        try:
            first = start(self.home)
            self.assertEqual(Client(port).request("/health", raw=True), b"OK")
            self.assertTrue(start(self.home)["alreadyRunning"])
            self.assertTrue(stop(self.home)["stopping"])
            deadline = time.monotonic() + 20
            while (
                self.home / ".godel/tracking-service.json"
            ).exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse((self.home / ".godel/tracking-service.json").exists())
            second = start(self.home)
            self.assertNotEqual(first["pid"], second["pid"])
            self.assertEqual(Client(port).request("/health", raw=True), b"OK")
        finally:
            stop(self.home)
            deadline = time.monotonic() + 20
            while (
                self.home / ".godel/tracking-service.json"
            ).exists() and time.monotonic() < deadline:
                time.sleep(0.1)

    @unittest.skipUnless(
        os.environ.get("GODEL_TEST_MLFLOW") == "1",
        "run make verify-tracking for a real local server",
    )
    def test_real_mlflow_retries_metrics_artifacts_and_failed_runs(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        atomic_json(self.home / ".godel/tracking.json", {"port": port})
        directory = self.home / "mlflow"
        directory.mkdir()
        env = local_environment()
        env.update(MLFLOW_ENABLE_TELEMETRY="false", DO_NOT_TRACK="true")
        command = [
            str(REPO / ".venv/bin/mlflow"),
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--backend-store-uri",
            "sqlite:///" + str(directory / "mlflow.db"),
            "--serve-artifacts",
            "--artifacts-destination",
            str(directory / "artifacts"),
            "--workers",
            "1",
        ]
        with (directory / "server.log").open("w") as log:
            process = subprocess.Popen(
                command, env=env, stdout=log, stderr=log, start_new_session=True
            )
            try:
                client = Client(port)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        client.request("/health", raw=True)
                        break
                    except OSError:
                        if process.poll() is not None:
                            self.fail((directory / "server.log").read_text()[-4000:])
                        time.sleep(0.2)
                else:
                    self.fail("MLflow did not become healthy")
                good, bad = self.run_example(), self.run_example(failed=True)
                self.assertEqual(len(good.get("metricHistory", [])), 2, good)
                self.assertEqual(len(bad.get("metricHistory", [])), 2, bad)
                # Simulate server success followed by a lost create response.
                original = Client.api
                dropped = False

                def lost_reply(instance, endpoint, *args, **kwargs):
                    nonlocal dropped
                    result = original(instance, endpoint, *args, **kwargs)
                    if endpoint == "runs/create" and not dropped:
                        dropped = True
                        raise ConnectionResetError("Simulated lost create acknowledgement")
                    return result

                with patch.object(Client, "api", lost_reply):
                    self.assertEqual(sync(self.home, force=True)["synced"], 0)
                self.assertEqual(sync(self.home, force=True)["synced"], 2)
                self.assertEqual(status(self.home)["pending"], 0)
                self.assertEqual(sync(self.home, force=True)["synced"], 0)
                for entry in status(self.home)["runs"]:
                    remote = client.api("runs/get", {"run_id": entry["mlflowRunId"]}, "GET")["run"]
                    expected = "FINISHED" if entry["runId"] == good["id"] else "FAILED"
                    self.assertEqual(remote["info"]["status"], expected)
                    remote_metrics = {
                        point["key"]: point["value"] for point in remote["data"]["metrics"]
                    }
                    self.assertEqual(remote_metrics["mse"], good["metrics"]["mse"])
                    history = client.api(
                        "metrics/get-history",
                        {
                            "run_id": entry["mlflowRunId"],
                            "metric_key": "train_loss",
                            "max_results": 1000,
                        },
                        "GET",
                    )
                    self.assertIn("metrics", history, {"history": history, "remote": remote})
                    self.assertEqual(
                        sorted((p["step"], p["value"]) for p in history["metrics"]),
                        [(1, 2.0), (2, 1.0)],
                    )
                    artifact_path = remote["info"]["artifact_uri"].removeprefix("mlflow-artifacts:")
                    downloaded = client.request(
                        "/api/2.0/mlflow-artifacts/artifacts" + artifact_path + "/model.json",
                        raw=True,
                    )
                    original_model = (
                        self.root / ".godel/runs" / entry["runId"] / "model.json"
                    ).read_bytes()
                    self.assertEqual(
                        hashlib.sha256(downloaded).digest(), hashlib.sha256(original_model).digest()
                    )
                    found = client.api(
                        "runs/search",
                        {
                            "experiment_ids": [remote["info"]["experiment_id"]],
                            "filter": f"tags.`godel.run_id` = '{entry['runId']}'",
                        },
                    )
                    self.assertEqual(len(found["runs"]), 1)
                # Replaying a completed export must not duplicate metric history.
                with self.store.connection() as db:
                    db.execute("UPDATE outbox SET synced_revision=0")
                self.assertEqual(sync(self.home, force=True)["synced"], 2)
                entry = status(self.home)["runs"][0]
                self.assertEqual(
                    len(
                        client.api(
                            "metrics/get-history",
                            {
                                "run_id": entry["mlflowRunId"],
                                "metric_key": "train_loss",
                                "max_results": 1000,
                            },
                            "GET",
                        )["metrics"]
                    ),
                    2,
                )
                # Remote GPU lifecycle through the same offline queue and server.
                request, registered, finish = self.remote_example()
                self.assertEqual(sync(self.home, force=True)["synced"], 1)
                item = next(r for r in status(self.home)["runs"] if r["runId"] == registered["id"])
                remote_id = item["mlflowRunId"]
                self.assertEqual(
                    client.api("runs/get", {"run_id": remote_id}, "GET")["run"]["info"]["status"],
                    "RUNNING",
                )
                remote_run(self.root, finish)
                with patch.object(Client, "api", side_effect=ConnectionError("server down")):
                    self.assertEqual(sync(self.home, force=True)["synced"], 0)
                self.assertEqual(get_run(self.root, registered["id"])["metrics"]["mse"], 0.25)
                self.assertEqual(sync(self.home, force=True)["synced"], 1)
                remote = client.api("runs/get", {"run_id": remote_id}, "GET")["run"]
                self.assertEqual(remote["info"]["status"], "FINISHED")
                self.assertIn(
                    {"key": "godel.remote.version", "value": "11"}, remote["data"]["tags"]
                )
                self.assertEqual(
                    {m["key"]: m["value"] for m in remote["data"]["metrics"]}["mse"], 0.25
                )
                artifact_path = remote["info"]["artifact_uri"].removeprefix("mlflow-artifacts:")
                self.assertEqual(
                    client.request(
                        "/api/2.0/mlflow-artifacts/artifacts" + artifact_path + "/output.log",
                        raw=True,
                    ),
                    (self.root / "download.log").read_bytes(),
                )
                remote_run(self.root, request, "resumed")
                remote_run(self.root, finish, "resumed")
                self.assertEqual(sync(self.home, force=True)["synced"], 0)
                found = client.api(
                    "runs/search",
                    {
                        "experiment_ids": [remote["info"]["experiment_id"]],
                        "filter": f"tags.`godel.run_id` = '{registered['id']}'",
                    },
                )
                self.assertEqual(len(found["runs"]), 1)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


if __name__ == "__main__":
    unittest.main()
