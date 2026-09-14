"""Agent-owned remote execution: durable registration and explicit result import.

No remote API calls or credentials belong here. The agent verifies remote identity,
downloads evidence, and supplies project-relative files to this interface.
"""

import fcntl
import hashlib
import json
import math
from pathlib import Path
import uuid

from .experiments import _snapshots, collect_results, list_runs
from .projects import read_project
from .records import get_run, save_run
from .review import candidate_count
from .storage import atomic_json, now, text
from .tracking import valid_metric_name


def remote_run(root, request, session_id="manual", model=None, tool_call_id=None):
    root = Path(root).resolve()
    state = root / ".godel"
    state.mkdir(exist_ok=True)
    with (state / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another experiment operation is active; retry later.") from None
        if request.get("action") == "register":
            return _register(root, request, session_id, model, tool_call_id)
        if request.get("action") == "finish":
            return _finish(root, request, tool_call_id)
        raise ValueError("Remote action must be register or finish.")


def _register(root, request, session_id, model, tool_call_id):
    project = read_project(root)
    if project["evaluation"] is None:
        raise ValueError("Set the actual remote evaluation contract in project.json first.")
    identity = request.get("remote")
    if not isinstance(identity, dict) or set(identity) != {"platform", "jobId", "version"}:
        raise ValueError("remote requires platform, jobId and immutable version.")
    for key, value in identity.items():
        text(value, key, 300)
    text(request.get("hypothesis"), "hypothesis", 2000)
    sources = request.get("sources")
    if (
        not isinstance(sources, list)
        or not 1 <= len(sources) <= 32
        or any(not isinstance(s, str) for s in sources)
        or len(set(sources)) != len(sources)
    ):
        raise ValueError("sources requires 1–32 unique code/config paths.")
    declared = request.get("candidateCount")
    if type(declared) is not int or not 1 <= declared <= 1000:
        raise ValueError("candidateCount must be 1–1000.")
    parameters = request.get("parameters", {})
    if (
        not isinstance(parameters, dict)
        or len(parameters) > 80
        or any(
            not valid_metric_name(k)
            or type(v) not in (str, int, float, bool)
            or len(str(v)) > 500
            or (type(v) is float and not math.isfinite(v))
            for k, v in parameters.items()
        )
    ):
        raise ValueError("parameters must contain at most 80 named finite scalars.")
    run_id = str(uuid.uuid5(uuid.UUID(project["id"]), json.dumps(identity, sort_keys=True)))
    runs = list_runs(root)
    existing = next((r for r in runs if r["id"] == run_id), None)
    if existing:
        if existing["request"] != request:
            raise ValueError("Remote identity already registered with different metadata.")
        return existing
    if request.get("parentRunId"):
        get_run(root, request["parentRunId"])
    session_runs = [r for r in runs if r.get("sessionId") == session_id]
    if len(session_runs) >= project["maxRunsPerSession"]:
        raise ValueError("Session experiment budget exhausted.")
    cap = project.get("maxCandidatesPerSession")
    if cap is not None and sum(candidate_count(r) for r in session_runs) + declared > cap:
        raise ValueError("Session candidate budget exhausted.")
    run_dir = root / ".godel/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshots = _snapshots(root, run_dir, sources)
    record = dict(
        schemaVersion=1,
        id=run_id,
        projectId=project["id"],
        sessionId=session_id,
        model=model,
        toolCallId=tool_call_id,
        request=request,
        remote=identity,
        evaluation=project["evaluation"],
        startedAt=now(),
        status="running",
        measurement="pending",
        sources=snapshots,
    )
    atomic_json(run_dir / "run.json", record)
    save_run(root, record)
    return record


def _finish(root, request, tool_call_id):
    record = get_run(root, request["runId"])
    if not record.get("remote") or request.get("remote") != record["remote"]:
        raise ValueError("Result identity must match the registered remote platform/job/version.")
    status = request.get("status")
    if status not in ("succeeded", "failed", "cancelled", "timed_out"):
        raise ValueError("Provide the observed terminal remote status, not push/download status.")
    text(request.get("provenance"), "provenance", 4000)
    files = request.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= 100 or "output.log" not in files:
        raise ValueError(
            "files maps artifact names to downloaded project paths; output.log is required."
        )
    contents, total = {}, 0
    for name, source in files.items():
        text(name, "artifact name", 200)
        text(source, "artifact source", 500)
        path = Path(source)
        if (
            Path(name).name != name
            or name in (".", "..", "run.json", "sources", "remote-result.json")
            or name.startswith(".")
            or path.is_absolute()
            or any(
                p in ("..", ".git", ".godel", "node_modules") or p.startswith(".env")
                for p in path.parts
            )
        ):
            raise ValueError("Use safe artifact basenames and project-relative result files.")
        original = root / path
        if any(p.is_symlink() for p in (original, *original.parents)):
            raise ValueError("Result files must not use symlinks.")
        resolved = original.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("Result source must be a regular file inside the project.")
        total += resolved.stat().st_size
        if total > 64 * 1024 * 1024:
            raise ValueError(
                "Result import exceeds 64 MiB; use checksummed references for large models."
            )
        contents[name] = resolved.read_bytes()
    manifest = dict(
        remote=record["remote"],
        status=status,
        provenance=request["provenance"],
        sha256={k: hashlib.sha256(v).hexdigest() for k, v in contents.items()},
    )
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    if record["status"] != "running":
        if record.get("resultDigest") != digest:
            raise ValueError("Terminal remote results are immutable; conflicting import rejected.")
        return record
    run_dir = root / ".godel/runs" / record["id"]
    # Before touching artifacts, persist the import intent. A crash/retry may only
    # finish this same bundle, so partially copied files cannot leak into a later one.
    if record.get("resultDigest") not in (None, digest):
        raise ValueError("Retry the original result bundle; an import is already pending.")
    record["resultDigest"] = digest
    atomic_json(run_dir / "run.json", record)
    save_run(root, record)
    for name, content in contents.items():
        (run_dir / name).write_bytes(content)
    atomic_json(run_dir / "remote-result.json", manifest)
    record.update(status=status, finishedAt=now(), resultToolCallId=tool_call_id)
    return collect_results(root, record)
