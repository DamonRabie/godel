"""Bounded local execution with separate process status and metric validity."""

import fcntl
import hashlib
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
import uuid

from .projects import read_project
from .runtime import local_environment
from .review import candidate_count, review_run
from .storage import atomic_json, now, read_json, text
from .records import get_run, project_store, save_run
from .tracking import valid_metric_name

LOG_LIMIT = 2 * 1024 * 1024
SNAPSHOT_LIMIT = 4 * 1024 * 1024


def list_runs(root):
    store = project_store(root)
    project = read_project(root)
    with store.connection() as db:
        known = {
            row[0] for row in db.execute("SELECT id FROM runs WHERE project_id=?", (project["id"],))
        }
    for file in (Path(root) / ".godel" / "runs").glob("*/run.json"):
        if file.parent.name in known:
            continue
        run = read_json(file)
        if (
            run.get("schemaVersion") != 1
            or run.get("id") != file.parent.name
            or run.get("projectId") != project["id"]
        ):
            raise ValueError(f"Invalid run record: {file}")
        save_run(root, run)
    with store.connection() as db:
        import json

        return [
            json.loads(row[0])
            for row in db.execute(
                "SELECT body FROM runs WHERE project_id=? ORDER BY started_at DESC",
                (project["id"],),
            )
        ]


def comparable(run, evaluation):
    return (
        run["status"] == "succeeded"
        and run["measurement"] == "valid"
        and run.get("evidenceReview", {}).get("status") != "inconsistent"
        and run["evaluation"] == evaluation
    )


def _snapshots(root, run_dir, sources):
    hashes, total = {}, 0
    for source in sources:
        text(source, "source path", 500)
        path = Path(source)
        if path.is_absolute() or any(
            part in ("..", ".godel", ".git", "node_modules") or part.startswith(".env")
            for part in path.parts
        ):
            raise ValueError(
                f"Snapshot sources must be project-relative code/config files: {source}"
            )
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError(f"Source is outside the project or not a file: {source}")
        total += resolved.stat().st_size
        if total > SNAPSHOT_LIMIT:
            raise ValueError(
                "Source snapshots exceed 4 MiB; select only relevant code/config files."
            )
        content = resolved.read_bytes()
        hashes[source] = hashlib.sha256(content).hexdigest()
        destination = run_dir / "sources" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return hashes


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_experiment(root, request, session_id="manual", model=None, tool_call_id=None):
    root = Path(root).resolve()
    project = read_project(root)
    if project["evaluation"] is None:
        raise ValueError(
            "Set project.json evaluation (datasetId, splitId, metric, direction) before running experiments."
        )
    text(request.get("hypothesis"), "hypothesis", 2000)
    parameters = request.get("parameters", {})
    if (
        not isinstance(parameters, dict)
        or len(parameters) > 80
        or any(
            not valid_metric_name(key)
            or type(value) not in (str, int, float, bool)
            or len(str(value)) > 500
            or (type(value) is float and not math.isfinite(value))
            for key, value in parameters.items()
        )
    ):
        raise ValueError(
            "parameters must map at most 80 MLflow-compatible names to finite scalar values (500 characters each)."
        )
    command = request.get("command")
    sources = request.get("sources")
    if not isinstance(command, list) or not 1 <= len(command) <= 100:
        raise ValueError("command must be a nonempty argv list; shell expansion is not performed.")
    for part in command:
        text(part, "command argument", 4000)
    if (
        not isinstance(sources, list)
        or not 1 <= len(sources) <= 32
        or len(set(sources)) != len(sources)
    ):
        raise ValueError("sources must list 1–32 unique code/config paths to snapshot.")
    timeout = request.get("timeoutSeconds")
    declared = request.get("candidateCount")
    if declared is not None and (type(declared) is not int or not 1 <= declared <= 1000):
        raise ValueError("candidateCount must be an integer between 1 and 1000.")
    if project.get("maxCandidatesPerSession") is not None and declared is None:
        raise ValueError("Declare candidateCount when a candidate budget is configured.")
    if type(timeout) is not int or not 1 <= timeout <= project["maxRunSeconds"]:
        raise ValueError(
            f"Run exceeds project budget; timeoutSeconds must be 1–{project['maxRunSeconds']}."
        )
    if request.get("parentRunId"):
        parent = get_run(root, request["parentRunId"])
        if parent["projectId"] != project["id"]:
            raise ValueError("Parent run belongs to a different project.")
    state = root / ".godel"
    state.mkdir(exist_ok=True)
    with (state / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                "Another experiment is running in this project; wait for it to finish."
            ) from None
        session_runs = [run for run in list_runs(root) if run.get("sessionId") == session_id]
        if len(session_runs) >= project["maxRunsPerSession"]:
            raise ValueError(
                "Session experiment budget exhausted. Review results with the user before changing the budget or starting a new session."
            )
        cap = project.get("maxCandidatesPerSession")
        if cap is not None and sum(candidate_count(run) for run in session_runs) + declared > cap:
            raise ValueError(
                "Session candidate budget exhausted; batches count each candidate, including failed attempts."
            )
        return _execute(root, project, request, session_id, model, tool_call_id)


def _execute(root, project, request, session_id, model, tool_call_id):
    run_id = str(uuid.uuid4())
    run_dir = root / ".godel" / "runs" / run_id
    run_dir.mkdir(parents=True)
    record = dict(
        schemaVersion=1,
        id=run_id,
        projectId=project["id"],
        sessionId=session_id,
        model=model,
        toolCallId=tool_call_id,
        request=request,
        evaluation=project["evaluation"],
        startedAt=now(),
        status="running",
        measurement="pending",
        sources={},
    )
    path = run_dir / "run.json"
    atomic_json(path, record)
    save_run(root, record)
    started = time.monotonic()
    cancel = threading.Event()
    handlers = {}
    process = None
    try:
        record["sources"] = _snapshots(root, run_dir, request["sources"])
        # The adapter's cancellation sends SIGTERM to this Python process.
        # Finish the record and kill experiment descendants before returning.
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                handlers[sig] = signal.signal(sig, lambda *_: cancel.set())
        env = local_environment()
        env["GODEL_RUN_DIR"] = str(run_dir)
        if request.get("candidateCount") is not None:
            env["GODEL_CANDIDATE_COUNT"] = str(request["candidateCount"])
        process = subprocess.Popen(
            request["command"],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        record["pid"] = process.pid
        atomic_json(path, record)
        save_run(root, record)
        timed_out, kept = False, 0
        with selectors.DefaultSelector() as selector, (run_dir / "output.log").open("wb") as log:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if cancel.is_set() or time.monotonic() - started > request["timeoutSeconds"]:
                    timed_out = not cancel.is_set()
                    _kill_group(process)
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        break
                    retained = chunk[: max(0, LOG_LIMIT - kept)]
                    log.write(retained)
                    kept += len(retained)
                    if len(retained) < len(chunk):
                        record["logTruncated"] = True
                if process.poll() is not None:
                    _kill_group(process)
            # A program may close stdout early but keep computing.
            while process.poll() is None:
                if cancel.is_set() or time.monotonic() - started > request["timeoutSeconds"]:
                    timed_out = not cancel.is_set()
                    _kill_group(process)
                time.sleep(0.02)
        record["exitCode"] = process.wait()
        record["status"] = (
            "cancelled"
            if cancel.is_set()
            else "timed_out"
            if timed_out
            else "succeeded"
            if record["exitCode"] == 0
            else "failed"
        )
    except Exception as error:
        record.update(status="failed", error=str(error))
    finally:
        if process:
            _kill_group(process)
            process.wait()
            process.stdout.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        record.update(finishedAt=now(), durationSeconds=round(time.monotonic() - started, 3))
    return collect_results(root, record)


def collect_results(root, record):
    """Validate local or imported measurements using the frozen evaluation contract."""
    run_dir = Path(root) / ".godel" / "runs" / record["id"]
    path = run_dir / "run.json"
    record["measurement"] = "missing"
    metrics_file = run_dir / "metrics.json"
    if metrics_file.exists():
        try:
            if (
                metrics_file.is_symlink()
                or not metrics_file.is_file()
                or metrics_file.stat().st_size > 65536
            ):
                raise ValueError("metrics.json must be a regular file smaller than 64 KiB.")
            metrics = read_json(metrics_file)
            if (
                not isinstance(metrics, dict)
                or not metrics
                or not all(
                    type(value) in (int, float) and math.isfinite(value)
                    for value in metrics.values()
                )
                or record["evaluation"]["metric"] not in metrics
            ):
                raise ValueError(
                    "metrics.json must map names to finite numbers and include the primary metric."
                )
            record.update(metrics=metrics, measurement="valid")
        except (ValueError, OSError) as error:
            record.update(measurement="invalid", metricError=str(error))
    record["evidenceReview"] = review_run(root, record)
    record["trackingWarnings"] = []
    history_file = run_dir / "metric-history.json"
    if history_file.exists():
        try:
            if (
                history_file.is_symlink()
                or not history_file.is_file()
                or history_file.stat().st_size > 4 * 1024 * 1024
            ):
                raise ValueError("metric-history.json must be a regular file under 4 MiB.")
            points = read_json(history_file)
            if not isinstance(points, list) or len(points) > 10000:
                raise ValueError("metric-history.json must be a list of at most 10000 points.")
            seen = set()
            for point in points:
                if (
                    not isinstance(point, dict)
                    or type(point.get("step")) is not int
                    or point["step"] < 0
                    or not isinstance(point.get("metrics"), dict)
                    or not 1 <= len(point["metrics"]) <= 32
                ):
                    raise ValueError(
                        "Metric history points need a nonnegative step and 1–32 metrics."
                    )
                for key, value in point["metrics"].items():
                    if (
                        not valid_metric_name(key)
                        or type(value) not in (int, float)
                        or not math.isfinite(value)
                        or (key, point["step"]) in seen
                    ):
                        raise ValueError(
                            "Metric history requires valid names, finite values and unique metric/step pairs."
                        )
                    seen.add((key, point["step"]))
            record["metricHistory"] = points
        except (ValueError, OSError) as error:
            record["trackingWarnings"].append(str(error))
    if any(not valid_metric_name(key) for key in record.get("metrics", {})):
        record["trackingWarnings"].append(
            "Some metric names cannot be plotted in MLflow; all remain in the run artifact."
        )
    atomic_json(path, record)
    save_run(root, record)
    return record
