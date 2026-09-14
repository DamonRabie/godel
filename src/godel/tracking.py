"""Local MLflow projection with an offline, transactional retry queue.

The harness uses only stdlib HTTP. MLflow itself runs in the workspace venv.
"""

from datetime import datetime
import fcntl
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import quote, urlencode, urlsplit

from .runtime import local_environment
from .storage import Store, atomic_json, read_json

DEFAULT_PORT = 5050


def settings(home):
    path = Path(home) / ".godel/tracking.json"
    config = read_json(path) if path.exists() else {}
    port = config.get("port", DEFAULT_PORT)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Tracking port must be an integer between 1024 and 65535.")
    return {
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "database": str(Path(home).resolve() / "mlflow/mlflow.db"),
        "artifacts": str(Path(home).resolve() / "mlflow/artifacts"),
    }


class TrackingError(Exception):
    pass


class Client:
    def __init__(self, port):
        self.port = port

    def request(
        self,
        endpoint,
        payload=None,
        method=None,
        *,
        file=None,
        raw=False,
        body_bytes=None,
        extra_headers=None,
    ):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = (
            file
            if file is not None
            else json.dumps(payload).encode()
            if payload is not None
            else None
        )
        if body_bytes is not None:
            body = body_bytes
        headers = {"Content-Type": "application/octet-stream" if file else "application/json"}
        headers.update(extra_headers or {})
        if file:
            headers["Content-Length"] = str(os.fstat(file.fileno()).st_size)
        try:
            connection.request(
                method or ("POST" if payload is not None else "GET"), endpoint, body, headers
            )
            response = connection.getresponse()
            data = response.read()
            if response.status >= 400:
                # Do not echo payloads or arbitrary server responses into context.
                try:
                    code = json.loads(data).get("error_code", "HTTP_ERROR")
                except (ValueError, AttributeError):
                    code = "HTTP_ERROR"
                raise TrackingError(f"MLflow HTTP {response.status}: {code}")
            return data if raw else json.loads(data) if data else {}
        finally:
            connection.close()

    def api(self, endpoint, payload=None, method=None):
        if method == "GET" and payload:
            endpoint += "?" + urlencode(payload)
            payload = None
        return self.request("/api/2.0/mlflow/" + endpoint, payload, method)


def _milliseconds(value):
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def _experiment(client, project_id, project_name):
    name = f"godel / {project_name}"
    try:
        experiment = client.api("experiments/get-by-name", {"experiment_name": name}, "GET")[
            "experiment"
        ]
        if not any(
            t["key"] == "godel.project_id" and t["value"] == project_id
            for t in experiment.get("tags", [])
        ):
            raise TrackingError("Experiment name belongs to another project.")
        return experiment["experiment_id"]
    except TrackingError as error:
        if "RESOURCE_DOES_NOT_EXIST" not in str(error):
            raise
    return client.api(
        "experiments/create",
        {
            "name": name,
            "tags": [
                {"key": "godel.project_id", "value": project_id},
                {"key": "godel.project_name", "value": project_name},
                {"key": "godel.layout", "value": "project-v1"},
            ],
        },
    )["experiment_id"]


def project_experiment(client, store, project):
    """One durable mapping shared by trace and training exporters."""
    with (store.path.parent / "project-experiment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with store.connection() as db:
            row = db.execute(
                "SELECT experiment_id FROM history_projects WHERE project_id=?", (project["id"],)
            ).fetchone()
        if row:
            experiment = client.api("experiments/get", {"experiment_id": row[0]}, "GET")[
                "experiment"
            ]
            tags = {tag["key"]: tag["value"] for tag in experiment.get("tags", [])}
            if (
                tags.get("godel.project_id") != project["id"]
                or experiment.get("lifecycle_stage") != "active"
            ):
                raise TrackingError(
                    "Mapped experiment is not active or belongs to another project; export retained in queue."
                )
            return row[0]
        experiment_id = _experiment(client, project["id"], project["name"])
        client.api(
            "experiments/set-experiment-tag",
            {
                "experiment_id": experiment_id,
                "key": "mlflow.note.content",
                "value": project["goal"],
            },
        )
        with store.connection() as db:
            db.execute("INSERT INTO history_projects VALUES (?, ?)", (project["id"], experiment_id))
        return experiment_id


def _remote_run(client, store, record, experiment_id, remote_id):
    if remote_id:
        return client.api("runs/get", {"run_id": remote_id}, "GET")["run"]
    # Recover a create whose HTTP reply or local acknowledgement was lost.
    found = client.api(
        "runs/search",
        {
            "experiment_ids": [experiment_id],
            "filter": f"tags.`godel.run_id` = '{record['id']}'",
            "max_results": 2,
        },
    ).get("runs", [])
    if len(found) > 1:
        raise TrackingError(
            "Multiple MLflow runs have the same Godel ID; reconcile them before retrying."
        )
    remote = (
        found[0]
        if found
        else client.api(
            "runs/create",
            {
                "experiment_id": experiment_id,
                "start_time": _milliseconds(record["startedAt"]),
                "run_name": record["request"]["hypothesis"][:200],
                "tags": [{"key": "godel.run_id", "value": record["id"]}],
            },
        )["run"]
    )
    with store.connection() as db:
        db.execute(
            "UPDATE outbox SET remote_id=?, experiment_id=? WHERE run_id=?",
            (remote["info"]["run_id"], experiment_id, record["id"]),
        )
    return remote


def _export(client, store, row):
    run_id, revision, encoded, directory, remote_id, experiment_id = row
    record = json.loads(encoded)
    root = Path(directory).parents[2]
    # Only the persisted run directory is exported, never project or auth folders.
    if Path(directory).is_symlink() or Path(directory).resolve() != Path(directory):
        raise TrackingError("Run artifact directory must not contain symlinks.")
    project = read_json(root / "project.json")
    destination = project_experiment(client, store, project)
    if experiment_id is not None and experiment_id != destination:
        raise TrackingError(
            "Run and project experiment mappings disagree; export retained in queue."
        )
    experiment_id = destination
    remote = _remote_run(client, store, record, experiment_id, remote_id)
    remote_id = remote["info"]["run_id"]
    tags = {
        "godel.project_id": record["projectId"],
        "godel.session_id": record["sessionId"],
        "godel.status": record["status"],
        "godel.measurement": record["measurement"],
        "godel.evidence_review": record.get("evidenceReview", {}).get("status", "pending"),
        "godel.hypothesis": record["request"]["hypothesis"],
        "godel.parent_run_id": record["request"].get("parentRunId", ""),
        "godel.tool_call_id": record.get("toolCallId") or "",
        "godel.model": json.dumps(record.get("model")),
        "godel.tracking_warnings": json.dumps(record.get("trackingWarnings", [])),
    }
    tags.update({f"godel.remote.{key}": value for key, value in record.get("remote", {}).items()})
    params = {
        **{f"evaluation.{key}": str(value) for key, value in record["evaluation"].items()},
        **{
            f"parameter.{key}": str(value)
            for key, value in record["request"].get("parameters", {}).items()
        },
    }
    stamp = _milliseconds(record.get("finishedAt", record["startedAt"]))
    final_steps = {}
    for point in record.get("metricHistory", []):
        for key in point["metrics"]:
            final_steps[key] = max(final_steps.get(key, 0), point["step"] + 1)
    metrics = [
        {"key": key, "value": value, "timestamp": stamp, "step": final_steps.get(key, 0)}
        for key, value in record.get("metrics", {}).items()
        if valid_metric_name(key)
    ]
    for point in record.get("metricHistory", []):
        metrics.extend(
            {
                "key": key,
                "value": value,
                "timestamp": _milliseconds(record["startedAt"]),
                "step": point["step"],
            }
            for key, value in point["metrics"].items()
        )
    # Exact timestamp/step/value replay is deduplicated by MLflow's SQL store.
    for offset in range(0, max(1, len(metrics)), 500):
        client.api(
            "runs/log-batch",
            {
                "run_id": remote_id,
                "metrics": metrics[offset : offset + 500],
                "params": [{"key": key, "value": value} for key, value in params.items()]
                if offset == 0
                else [],
                "tags": [{"key": key, "value": str(value)} for key, value in tags.items()]
                if offset == 0
                else [],
            },
        )
    # Never upload artifacts while the experiment is still writing them.
    if record["status"] != "running":
        uri = urlsplit(remote["info"]["artifact_uri"])
        if uri.scheme != "mlflow-artifacts" or uri.netloc or ".." in Path(uri.path).parts:
            raise TrackingError("Expected this server's local proxied MLflow artifact store.")
        for path in sorted(Path(directory).rglob("*")):
            if path.is_symlink() or not path.is_file() or path.resolve() != path:
                continue
            relative = path.relative_to(directory).as_posix()
            endpoint = "/api/2.0/mlflow-artifacts/artifacts/" + quote(
                uri.path.strip("/") + "/" + relative, safe="/"
            )
            with path.open("rb") as stream:
                client.request(endpoint, method="PUT", file=stream, raw=True)
        status = {
            "succeeded": "FINISHED",
            "failed": "FAILED",
            "cancelled": "KILLED",
            "timed_out": "KILLED",
        }[record["status"]]
        client.api("runs/update", {"run_id": remote_id, "status": status, "end_time": stamp})
    with store.connection() as db:
        db.execute(
            "UPDATE outbox SET synced_revision=?, last_error=NULL, attempts=0, next_attempt=0 "
            "WHERE run_id=?",
            (revision, run_id),
        )


def valid_metric_name(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 200
        and re.fullmatch(r"[\w. /-]+", value) is not None
        and ".." not in value
    )


def sync(home, *, force=False, limit=20):
    """One worker per workspace; no transaction spans a network request."""
    store = Store(home)
    with (Path(home) / ".godel/tracking-sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"synced": 0, "busy": True}
        with store.connection() as db:
            rows = db.execute(
                "SELECT r.id, o.revision, r.body, r.artifact_dir, o.remote_id, o.experiment_id "
                "FROM outbox o JOIN runs r ON r.id=o.run_id WHERE o.revision>o.synced_revision "
                "AND (? OR o.next_attempt<=?) ORDER BY r.started_at LIMIT ?",
                (force, time.time(), limit),
            ).fetchall()
        client, count = Client(settings(home)["port"]), 0
        for row in rows:
            try:
                _export(client, store, row)
                count += 1
            except (
                OSError,
                ValueError,
                KeyError,
                http.client.HTTPException,
                TrackingError,
            ) as error:
                with store.connection() as db:
                    db.execute(
                        "UPDATE outbox SET attempts=attempts+1, last_error=?, "
                        "next_attempt=? + min(300, 5 * (1 << min(attempts, 6))) WHERE run_id=?",
                        (str(error)[:500], time.time(), row[0]),
                    )
                # An unavailable server should not cause one timeout per queued run.
                if isinstance(error, (OSError, http.client.HTTPException)):
                    break
        return {"synced": count, "busy": False}


def status(home, project_id=None):
    store = Store(home)
    with store.connection() as db:
        rows = db.execute(
            "SELECT r.id, o.revision, o.synced_revision, o.remote_id, o.experiment_id, "
            "o.attempts, o.last_error FROM outbox o JOIN runs r ON r.id=o.run_id "
            "WHERE (? IS NULL OR r.project_id=?) ORDER BY r.started_at DESC",
            (project_id, project_id),
        ).fetchall()
        history = db.execute(
            "SELECT count(*),coalesce(sum(delivered=0),0) FROM history_refs "
            "WHERE ? IS NULL OR project_id=?",
            (project_id, project_id),
        ).fetchone()
        history_errors = db.execute(
            "SELECT p.id,p.error,p.attempts FROM pending_history p "
            "JOIN history_refs h ON h.id=p.id WHERE p.error IS NOT NULL "
            "AND (? IS NULL OR h.project_id=?) LIMIT 5",
            (project_id, project_id),
        ).fetchall()
    config = settings(home)
    return {
        **config,
        "pending": sum(row[1] > row[2] for row in rows),
        "history": {
            "store": "mlflow",
            "delivered": history[0] - history[1],
            "pending": history[1],
            "errors": [dict(eventId=r[0], error=r[1], attempts=r[2]) for r in history_errors],
        },
        "synced": sum(row[1] == row[2] for row in rows),
        "runs": [
            dict(
                runId=row[0],
                pending=row[1] > row[2],
                mlflowRunId=row[3],
                attempts=row[5],
                error=row[6],
                url=f"{config['url']}/#/experiments/{row[4]}/runs/{row[3]}" if row[3] else None,
            )
            for row in rows[:20]
        ],
    }


def serve(home):
    """Foreground service: local MLflow plus queue polling; Ctrl-C stops both."""
    home = Path(home).resolve()
    config = settings(home)
    binary = home / ".venv/bin/mlflow"
    if not binary.exists():
        raise ValueError("Run make setup-tracking to install the pinned local MLflow server.")
    Store(home)
    directory = home / "mlflow"
    directory.mkdir(exist_ok=True, mode=0o700)
    (directory / "artifacts").mkdir(exist_ok=True, mode=0o700)
    with (home / ".godel/tracking-server.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Godel's tracking service is already running.") from None
        # Refuse an occupied port before any export can reach another service.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", config["port"]))
        env = local_environment()
        env.update(MLFLOW_ENABLE_TELEMETRY="false", DO_NOT_TRACK="true")
        command = [
            str(binary),
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            str(config["port"]),
            "--backend-store-uri",
            "sqlite:///" + config["database"],
            "--serve-artifacts",
            "--artifacts-destination",
            config["artifacts"],
            "--workers",
            "1",
        ]
        stopped = False

        def stop(*_):
            nonlocal stopped
            stopped = True

        handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        process = subprocess.Popen(command, cwd=home, env=env, start_new_session=True)
        service_file = home / ".godel/tracking-service.json"
        bridge = None
        try:
            atomic_json(
                service_file, {"pid": os.getpid(), "identity": _process_identity(os.getpid())}
            )
            client = Client(config["port"])
            deadline = time.monotonic() + 60
            while process.poll() is None and not stopped:
                try:
                    client.request("/health", raw=True)
                    break
                except (OSError, TrackingError, http.client.HTTPException):
                    if time.monotonic() > deadline:
                        raise ValueError("MLflow did not become healthy within 60 seconds.")
                    time.sleep(0.5)
            if not stopped and process.poll() is None:
                bridge_env = dict(env, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
                bridge = subprocess.Popen(
                    [str(home / ".venv/bin/python"), "-m", "godel.service", "--home", str(home)],
                    cwd=home,
                    env=bridge_env,
                    start_new_session=True,
                )
            while process.poll() is None and not stopped:
                if bridge is not None and bridge.poll() is not None:
                    raise ValueError(
                        "The history bridge exited; restart tracking and inspect the service log."
                    )
                sync(home)
                for _ in range(10):
                    if stopped or process.poll() is not None:
                        break
                    time.sleep(0.5)
            if process.poll() not in (None, 0) and not stopped:
                raise ValueError(
                    f"MLflow server exited with code {process.returncode}; check its output."
                )
        finally:
            if bridge and bridge.poll() is None:
                bridge.terminate()
                try:
                    bridge.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    bridge.kill()
                    bridge.wait()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            service_file.unlink(missing_ok=True)


def _process_identity(pid):
    return subprocess.check_output(
        ["ps", "-p", str(pid), "-o", "lstart=,command="], text=True
    ).strip()


def start(home):
    """Start the service detached, retaining logs and an owned process identity."""
    home = Path(home).resolve()
    Store(home)
    with (home / ".godel/tracking-server.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"url": settings(home)["url"], "alreadyRunning": True}
    log_path = home / ".godel/tracking-server.log"
    with log_path.open("a") as log:
        log_path.chmod(0o600)
        process = subprocess.Popen(
            [sys.executable, str(home / "bin/godel.py"), "tracking", "serve"],
            cwd=home,
            env=local_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    client = Client(settings(home)["port"])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError(f"Tracking service did not start. Inspect {log_path}")
        try:
            client.request("/health", raw=True)
            # Ensure this launch owns the workspace service, not a competing start.
            service = read_json(home / ".godel/tracking-service.json")
            if service["pid"] == process.pid and (home / ".godel/api.sock").exists():
                threading.Thread(target=process.wait, daemon=True).start()
                return {"url": settings(home)["url"], "pid": process.pid, "log": str(log_path)}
        except (OSError, TrackingError, http.client.HTTPException):
            pass
        time.sleep(0.5)
    process.terminate()
    process.wait(timeout=15)
    raise ValueError(f"Tracking service did not become ready. Inspect {log_path}")


def stop(home):
    path = Path(home) / ".godel/tracking-service.json"
    if not path.exists():
        return {"stopped": False, "reason": "No recorded service process."}
    service = read_json(path)
    try:
        identity = _process_identity(service["pid"])
    except subprocess.CalledProcessError:
        return {"stopped": False, "reason": "Recorded process has exited."}
    if identity != service["identity"]:
        raise ValueError("Recorded PID belongs to a different process; refusing to signal it.")
    os.kill(service["pid"], signal.SIGTERM)
    return {"stopping": True, "pid": service["pid"]}
