"""Real MLflow history, single-copy delivery, restart and retrieval contracts."""

import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from godel.history import append_event, snapshot_native, restore_native
from godel.records import project_store, query_history
from godel.storage import atomic_json
from godel.projects import init_project
from godel.trace_delivery import flush
from godel.traces import client, read_event, invalidate
from godel.tracking import start, stop


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=30)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


@unittest.skipUnless(os.environ.get("GODEL_TEST_MLFLOW") == "1", "requires make verify-tracking")
class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="godel-traces-")
        cls.home = Path(cls.temp.name).resolve()
        shutil.copytree(REPO / "templates", cls.home / "templates")
        cls.root, cls.project = init_project(cls.home, "history", "Preserve history")
        cls.store = project_store(cls.root)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        atomic_json(cls.home / ".godel/tracking.json", {"port": port})
        (cls.home / ".venv").symlink_to(REPO / ".venv", target_is_directory=True)
        (cls.home / "bin").mkdir()
        (cls.home / "bin/godel.py").write_text(
            f"import sys\nfrom pathlib import Path\nsys.path.insert(0, {str(REPO / 'src')!r})\n"
            "from godel.tracking import serve\nserve(Path(__file__).resolve().parents[1])\n"
        )
        start(cls.home)

    @classmethod
    def tearDownClass(cls):
        stop(cls.home)
        deadline = time.monotonic() + 20
        while (cls.home / ".godel/tracking-service.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        cls.temp.cleanup()

    def setUp(self):
        self.session = str(uuid.uuid4())

    def drain(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            flush(self.home, force=True)
            with self.store.connection() as db:
                rows = db.execute("SELECT id,error FROM pending_history").fetchall()
            if not rows:
                return
            if any(row[1] for row in rows):
                self.fail(f"History delivery failed: {rows[:3]}")
            time.sleep(0.1)
        self.fail(f"History did not drain: {rows}")

    def call(self, action, payload):
        connection = UnixConnection(self.home / ".godel/api.sock")
        try:
            connection.request(
                "POST",
                "/",
                json.dumps({"project": str(self.root), "action": action, "payload": payload}),
                {"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            result = json.loads(response.read())
            self.assertEqual(response.status, 200, result)
            return result
        finally:
            connection.close()

    def test_delivery_search_pagination_large_payload_and_sessions(self):
        ids = []
        for type_, data in [
            (
                "input",
                {
                    "text": 'Find O\'Reilly baseline evidence فارسی \\"quoted\\"',
                    "empty": {},
                    "list": [],
                    "null": None,
                },
            ),
            ("model_call_start", {"model": {"id": "test"}}),
            (
                "message_end",
                {
                    "message": {
                        "role": "assistant",
                        "model": "test",
                        "content": [{"type": "text", "text": "baseline answer"}],
                    }
                },
            ),
            ("decision", {"summary": "Keep baseline", "rationale": "Measured", "evidenceRefs": []}),
            (
                "tool_end",
                {"toolCallId": "t", "toolName": "read", "result": "baseline large " * 10000},
            ),
            ("agent_end", {}),
        ]:
            ids.append(append_event(self.root, self.session, type_, data)["eventId"])
        self.drain()
        self.assertFalse((self.root / ".godel/history").exists())
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM pending_history").fetchone()[0], 0)
            keys = {
                row[0]
                for row in db.execute(
                    "SELECT trace_key FROM history_refs WHERE session_id=?", (self.session,)
                )
            }
        self.assertEqual(len(keys), 1)
        result = self.call(
            "history_search", {"sessionId": self.session, "query": "baseline", "limit": 2}
        )
        self.assertTrue(result["available"], result)
        self.assertEqual(len(result["events"]), 2)
        second = self.call(
            "history_search",
            {
                "sessionId": self.session,
                "query": "baseline",
                "after": result["nextCursor"],
                "limit": 2,
            },
        )
        self.assertEqual(len(second["events"]), 2, second)
        quoted = self.call("history_search", {"sessionId": self.session, "query": "O'Reilly"})
        self.assertEqual(len(quoted["events"]), 1, quoted)
        for query in ["فارسی", '\\"quoted\\"']:
            found = self.call("history_search", {"sessionId": self.session, "query": query})
            self.assertEqual(len(found["events"]), 1, found)
        offset, chunks = 0, []
        while True:
            event = read_event(self.store, self.project["id"], ids[4], offset, 20000)
            chunks.append(event["text"])
            if event["nextOffset"] is None:
                break
            offset = event["nextOffset"]
        self.assertEqual(json.loads("".join(chunks))["result"], "baseline large " * 10000)
        found = client(self.store).request(
            "/api/3.0/mlflow/traces/search",
            {
                "locations": [
                    {
                        "mlflow_experiment": {
                            "experiment_id": self.call("history", {})["url"]
                            .split("/experiments/")[1]
                            .split("/")[0]
                        }
                    }
                ],
                "filter": f"metadata.`mlflow.trace.session` = '{self.session}'",
                "max_results": 10,
            },
        )
        self.assertEqual(len(found["traces"]), 1, found)

    def test_ack_loss_is_idempotent_and_outage_is_explicit(self):
        id_ = append_event(self.root, self.session, "input", {"text": "retry evidence"})["eventId"]
        self.drain()
        with self.store.connection() as db:
            key = db.execute("SELECT trace_key FROM history_refs WHERE id=?", (id_,)).fetchone()[0]
        record = json.loads(read_event(self.store, self.project["id"], id_)["text"])
        from godel.traces import load_trace

        original = load_trace(self.store, key)[id_]
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO pending_history(id,body) VALUES (?,?)",
                (id_, json.dumps(original, ensure_ascii=False)),
            )
        self.drain()
        invalidate(self.store, key)
        self.assertEqual(len(load_trace(self.store, key)), 1)
        invalidate(self.store, key)
        with patch("godel.traces.Client.request", side_effect=ConnectionRefusedError("offline")):
            result = query_history(self.store, self.project["id"], session_id=self.session)
        self.assertFalse(result["available"])
        self.assertIn("not an empty history", result["error"])
        self.assertEqual(record["text"], "retry evidence")

    def test_native_resume_cache_can_be_rebuilt_exactly(self):
        directory = self.root / ".godel/sessions"
        directory.mkdir(parents=True, exist_ok=True)
        native = directory / f"test_{self.session}.jsonl"
        data = (
            "\n".join(
                json.dumps(item)
                for item in [
                    {
                        "type": "session",
                        "version": 3,
                        "id": self.session,
                        "timestamp": "2026-09-13T00:00:00Z",
                        "cwd": str(self.root),
                    },
                    {
                        "type": "message",
                        "id": "a",
                        "parentId": None,
                        "timestamp": "2026-09-13T00:00:01Z",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "Resume this branch"}],
                            "timestamp": 1,
                        },
                    },
                ]
            )
            + "\n"
        )
        native.write_text(data)
        snapshot_id = snapshot_native(self.root, self.session, native)
        self.drain()
        native.unlink()
        self.assertIn(native.name, restore_native(self.root))
        self.assertEqual(native.read_text(), data)
        self.assertEqual(restore_native(self.root), [])
        native.touch()
        self.assertEqual(snapshot_native(self.root, self.session, native), snapshot_id)

    def test_bridge_latency_and_context_parity(self):
        from godel.context import context

        expected = context(self.home, self.root)
        received = self.call("context", {})
        self.assertEqual(received, expected)
        subprocess_times = []
        code = (
            f"import sys;sys.path.insert(0,{str(REPO / 'src')!r});"
            "from pathlib import Path;from godel.cli import api;"
            f'api(Path({str(self.home)!r}),{str(self.root)!r},"event",'
            f'{{"sessionId":{str(uuid.uuid4())!r},"type":"input","data":{{"text":"baseline bridge"}}}})'
        )
        for _ in range(8):
            at = time.perf_counter()
            subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
            subprocess_times.append((time.perf_counter() - at) * 1000)
        times = []
        for n in range(30):
            at = time.perf_counter()
            self.call(
                "event",
                {"sessionId": self.session, "type": "input", "data": {"text": f"latency {n}"}},
            )
            times.append((time.perf_counter() - at) * 1000)
        self.drain()
        search = []
        for _ in range(10):
            at = time.perf_counter()
            result = self.call(
                "history_search", {"sessionId": self.session, "query": "latency", "limit": 10}
            )
            self.assertEqual(len(result["events"]), 10)
            search.append((time.perf_counter() - at) * 1000)
        print(
            json.dumps(
                {
                    "eventMedianMs": statistics.median(times),
                    "eventP95Ms": sorted(times)[28],
                    "subprocessMedianMs": statistics.median(subprocess_times),
                    "searchMedianMs": statistics.median(search),
                    "searchMaxMs": max(search),
                }
            )
        )
        self.assertLess(
            sorted(times)[28],
            100,
            "The persistent recording bridge must stay below a process-launch budget",
        )
        self.assertLess(statistics.median(search), 200, "History retrieval must remain interactive")
        self.assertLess(statistics.median(times), statistics.median(subprocess_times))

    def test_legacy_migration_is_verified_and_repeatable(self):
        from godel.migrate_history import migrate
        from godel.storage import now

        record = dict(
            schemaVersion=1,
            id=str(uuid.uuid4()),
            at=now(),
            projectId=self.project["id"],
            sessionId=self.session,
            type="input",
            data={"text": "legacy preserved"},
        )
        body = json.dumps(record, ensure_ascii=False)
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO events(id,project_id,session_id,type,at,body) VALUES (?,?,?,?,?,?)",
                (record["id"], self.project["id"], self.session, "input", record["at"], body),
            )
        journal = self.root / ".godel/history" / (self.session + ".jsonl")
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(body + "\n")
        result = migrate(self.home)
        self.assertTrue(result["complete"], result)
        self.assertTrue(Path(result["backup"]).exists())
        self.assertFalse(journal.exists())
        self.assertEqual(
            json.loads(read_event(self.store, self.project["id"], record["id"])["text"]),
            record["data"],
        )
        again = migrate(self.home)
        self.assertTrue(again["complete"], again)
        self.assertEqual(again["delivered"], result["delivered"])

    def test_project_contains_multiple_sessions_and_training_runs(self):
        from godel.experiments import run_experiment
        from godel.tracking import sync, status

        root, project = init_project(
            self.home, "unified", "One project with sessions and training runs"
        )
        project["evaluation"] = dict(
            datasetId="test", splitId="fixed", metric="mse", direction="minimize"
        )
        atomic_json(root / "project.json", project)
        ids = []
        for sid in (str(uuid.uuid4()), str(uuid.uuid4())):
            ids.append(
                append_event(root, sid, "input", {"text": "Preserve this user request"})["eventId"]
            )
            append_event(
                root,
                sid,
                "message_end",
                {
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Saved answer"}],
                    }
                },
            )
            append_event(root, sid, "agent_end", {})
        self.drain()
        run = run_experiment(
            root,
            {
                "hypothesis": "A recorded run belongs to its chat project",
                "command": [sys.executable, "-c", 'print("artifact evidence")'],
                "sources": ["pyproject.toml"],
                "timeoutSeconds": 5,
            },
            sid,
            tool_call_id="unified-tool",
        )
        sync(self.home, force=True)
        http = client(self.store)
        with self.store.connection() as db:
            destination = db.execute(
                "SELECT experiment_id FROM history_projects WHERE project_id=?", (project["id"],)
            ).fetchone()[0]
        remote_id = status(self.home, project["id"])["runs"][0]["mlflowRunId"]
        before = http.api("runs/get", {"run_id": remote_id}, "GET")["run"]
        self.assertEqual(before["info"]["experiment_id"], destination)
        tags = {t["key"]: t["value"] for t in before["data"]["tags"]}
        self.assertEqual(tags["godel.session_id"], sid)
        self.assertEqual(tags["godel.tool_call_id"], "unified-tool")
        self.assertEqual(
            http.api("experiments/get", {"experiment_id": destination}, "GET")["experiment"][
                "name"
            ],
            "godel / unified",
        )
        sync(self.home, force=True)
        after = http.api("runs/get", {"run_id": remote_id}, "GET")["run"]
        self.assertEqual(after, before)
        for event_id in ids:
            self.assertIn(
                "Preserve this user request",
                read_event(self.store, project["id"], event_id)["text"],
            )
        history = query_history(self.store, project["id"], query="Preserve this user request")
        self.assertEqual({e["id"] for e in history["events"]}, set(ids))
        artifacts = http.api("artifacts/list", {"run_id": remote_id}, "GET")["files"]
        self.assertTrue(any(f["path"] == "run.json" for f in artifacts))
        with self.store.connection() as db:
            self.assertEqual(
                db.execute(
                    "SELECT experiment_id FROM outbox WHERE run_id=?", (run["id"],)
                ).fetchone()[0],
                destination,
            )
        experiments = http.api(
            "experiments/search",
            {
                "view_type": 1,
                "max_results": 100,
                "filter": f"tags.`godel.project_id` = '{project['id']}'",
            },
        )["experiments"]
        self.assertEqual([e["experiment_id"] for e in experiments], [destination])
        run_experiment(
            root,
            {
                "hypothesis": "Second training attempt in the same project",
                "command": [sys.executable, "-c", 'print("second attempt")'],
                "sources": ["pyproject.toml"],
                "timeoutSeconds": 5,
            },
            sid,
            tool_call_id="second-tool",
        )
        sync(self.home, force=True)
        remote_runs = http.api("runs/search", {"experiment_ids": [destination]})["runs"]
        self.assertEqual(len(remote_runs), 2)
        traces = http.request(
            "/api/3.0/mlflow/traces/search",
            {
                "locations": [{"mlflow_experiment": {"experiment_id": destination}}],
                "max_results": 100,
            },
        )["traces"]
        self.assertEqual(len(traces), 2)
        # The reverse order must work too: training creates the container first.
        other, definition = init_project(
            self.home, "training-first", "Training before the first chat"
        )
        definition["evaluation"] = project["evaluation"]
        atomic_json(other / "project.json", definition)
        run_experiment(
            other,
            {
                "hypothesis": "Training first",
                "command": [sys.executable, "-c", 'print("first")'],
                "sources": ["pyproject.toml"],
                "timeoutSeconds": 5,
            },
            sid,
        )
        sync(self.home, force=True)
        append_event(other, sid, "input", {"text": "First chat after training"})
        append_event(other, sid, "agent_end", {})
        self.drain()
        with self.store.connection() as db:
            mapped = db.execute(
                "SELECT experiment_id FROM history_projects WHERE project_id=?", (definition["id"],)
            ).fetchone()[0]
        self.assertIn(
            "/experiments/" + mapped + "/", status(self.home, definition["id"])["runs"][0]["url"]
        )
        self.assertEqual(len(query_history(self.store, definition["id"])["events"]), 2)
        self.assertEqual(
            query_history(self.store, project["id"], query="First chat after training")["events"],
            [],
        )

    def test_project_creation_concurrency_lost_reply_and_name_collision(self):
        from godel.tracking import Client, TrackingError, project_experiment

        _, project = init_project(self.home, "concurrent", "Concurrent first exports")
        with ThreadPoolExecutor(max_workers=8) as pool:
            experiment_ids = list(
                pool.map(
                    lambda _: project_experiment(client(self.store), self.store, project), range(8)
                )
            )
        self.assertEqual(len(set(experiment_ids)), 1)
        http = client(self.store)
        experiments = http.api(
            "experiments/search",
            {
                "view_type": 1,
                "max_results": 100,
                "filter": f"tags.`godel.project_id` = '{project['id']}'",
            },
        )["experiments"]
        self.assertEqual(len(experiments), 1)

        # The server creates the experiment, but its response never arrives.
        _, retry = init_project(self.home, "create-retry", "Recover an ambiguous create")
        original = Client.api
        dropped = False

        def lost_reply(instance, endpoint, *args, **kwargs):
            nonlocal dropped
            result = original(instance, endpoint, *args, **kwargs)
            if endpoint == "experiments/create" and not dropped:
                dropped = True
                raise ConnectionResetError("Lost experiment creation response")
            return result

        with patch.object(Client, "api", lost_reply):
            with self.assertRaises(ConnectionResetError):
                project_experiment(http, self.store, retry)
        recovered = project_experiment(http, self.store, retry)
        experiments = http.api(
            "experiments/search",
            {
                "view_type": 1,
                "max_results": 100,
                "filter": f"tags.`godel.project_id` = '{retry['id']}'",
            },
        )["experiments"]
        self.assertEqual([e["experiment_id"] for e in experiments], [recovered])
        self.assertIn(
            {"key": "mlflow.note.content", "value": retry["goal"]}, experiments[0]["tags"]
        )
        # Simulate loss of just the local mapping: reuse the owned remote ID.
        with self.store.connection() as db:
            db.execute("DELETE FROM history_projects WHERE project_id=?", (retry["id"],))
        self.assertEqual(project_experiment(http, self.store, retry), recovered)
        # A different project cannot adopt an identically named experiment.
        other = dict(retry, id=str(uuid.uuid4()))
        with self.assertRaisesRegex(TrackingError, "another project"):
            project_experiment(http, self.store, other)
        with self.store.connection() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT experiment_id FROM history_projects WHERE project_id=?", (other["id"],)
                ).fetchone()
            )
            db.execute("INSERT INTO history_projects VALUES (?, ?)", (other["id"], recovered))
        try:
            with self.assertRaisesRegex(TrackingError, "another project"):
                project_experiment(http, self.store, other)
        finally:
            with self.store.connection() as db:
                db.execute("DELETE FROM history_projects WHERE project_id=?", (other["id"],))
        # Archiving a destination must not silently redirect future records.
        http.api("experiments/delete", {"experiment_id": recovered})
        try:
            with self.assertRaisesRegex(TrackingError, "not active"):
                project_experiment(http, self.store, retry)
        finally:
            http.api("experiments/restore", {"experiment_id": recovered})
        self.assertEqual(project_experiment(http, self.store, retry), recovered)

    def test_project_mapping_survives_service_restart_and_continued_session(self):
        from godel.tracking import project_experiment

        root, project = init_project(
            self.home, "restart", "Continue a session after service restart"
        )
        first = append_event(root, self.session, "input", {"text": "Before restart"})["eventId"]
        append_event(root, self.session, "agent_end", {})
        self.drain()
        destination = project_experiment(client(self.store), self.store, project)
        with self.store.connection() as db:
            keys = [
                r[0]
                for r in db.execute(
                    "SELECT trace_key FROM history_refs WHERE project_id=?", (project["id"],)
                )
            ]
        for key in keys:
            invalidate(self.store, key)
        stop(self.home)
        deadline = time.monotonic() + 20
        while (self.home / ".godel/tracking-service.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse((self.home / ".godel/tracking-service.json").exists())
        try:
            queued = append_event(root, self.session, "input", {"text": "Queued while stopped"})[
                "eventId"
            ]
            pending = query_history(self.store, project["id"], event_type="input", after=0)
            # Reading acknowledged history needs MLflow; outage must be explicit.
            self.assertFalse(pending["available"])
        finally:
            start(self.home)
        append_event(root, self.session, "agent_end", {})
        self.drain()
        self.assertEqual(project_experiment(client(self.store), self.store, project), destination)
        events = query_history(
            self.store, project["id"], session_id=self.session, event_type="input"
        )["events"]
        self.assertEqual([e["id"] for e in events], [first, queued])
        self.assertEqual(
            [e["data"]["text"] for e in events], ["Before restart", "Queued while stopped"]
        )
        traces = client(self.store).request(
            "/api/3.0/mlflow/traces/search",
            {
                "locations": [{"mlflow_experiment": {"experiment_id": destination}}],
                "max_results": 100,
            },
        )["traces"]
        self.assertEqual(len(traces), 2)
