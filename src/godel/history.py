"""Immediately durable conversation events, independent of Pi's lazy sessions."""

import fcntl
import hashlib
import json
from pathlib import Path
import uuid

from .projects import read_project
from .storage import identifier, now, text
from .records import project_store, save_event


def append_event(root, session_id, event_type, data):
    root = Path(root)
    project = read_project(root)
    identifier(session_id)
    text(event_type, "event type", 80)
    record = dict(
        schemaVersion=1,
        id=str(uuid.uuid4()),
        at=now(),
        projectId=project["id"],
        sessionId=session_id,
        type=event_type,
        data=data,
    )
    save_event(project_store(root), record)
    return {"eventId": record["id"], "historyStore": "mlflow", "delivery": "queued"}


def provenance(home):
    home = Path(home)
    paths = [
        home / "package-lock.json",
        home / "agent/system.md",
        home / "agent/model-development.md",
    ]
    paths += list((home / "agent/prompts").glob("*.md"))
    paths += list((home / "agent/skills").rglob("*.md"))
    paths += list((home / "agent/skills").rglob("*.py"))
    paths += list((home / "src/godel").glob("*.py"))
    paths += list((home / "pi").glob("*.ts"))
    return {
        str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
        if path.is_file()
    }


def list_history(root):
    root = Path(root)
    read_project(root)
    from .traces import sessions

    return {
        "project": root.name,
        "historyStore": "mlflow",
        **sessions(project_store(root), read_project(root)["id"]),
    }


def import_history(home):
    """Idempotently index legacy journals/runs without rewriting source files."""
    from .experiments import list_runs
    from .records import save_run
    from .storage import Store, read_json

    store = Store(home)
    result = {"eventsImported": 0, "runsIndexed": 0, "warnings": []}
    with store.connection() as db:
        old = db.execute("SELECT body FROM events ORDER BY sequence").fetchall()
    for (body,) in old:
        result["eventsImported"] += save_event(store, json.loads(body))
    for project_file in sorted((Path(home) / "projects").glob("*/project.json")):
        root = project_file.parent
        if not root.resolve().is_relative_to(Path(home).resolve()):
            result["warnings"].append(f"Skipped project outside workspace: {root.name}")
            continue
        project = read_project(root)
        # Index run evidence before importing decisions that reference it.
        runs = list_runs(root)
        for run in runs:
            if run["status"] == "running":
                disk = read_json(root / ".godel/runs" / run["id"] / "run.json")
                if disk.get("id") == run["id"] and disk.get("projectId") == project["id"]:
                    save_run(root, disk)
        result["runsIndexed"] += len(runs)
        for path in sorted((root / ".godel/history").glob("*.jsonl")):
            with path.open("rb") as stream:
                fcntl.flock(stream, fcntl.LOCK_SH)
                for number, line in enumerate(stream, 1):
                    try:
                        record = json.loads(line)
                        if (
                            not isinstance(record, dict)
                            or record.get("schemaVersion") != 1
                            or record.get("projectId") != project["id"]
                            or record.get("sessionId") != path.stem
                        ):
                            raise ValueError("Journal identity mismatch")
                        identifier(record["id"])
                        result["eventsImported"] += save_event(store, record)
                    except (ValueError, KeyError, TypeError) as error:
                        result["warnings"].append(
                            f"{root.name}/{path.name}:{number}: {type(error).__name__}; record preserved in original journal"
                        )
    return result


def snapshot_native(root, session_id, filename):
    """Store an exact Pi resume checkpoint in MLflow, treating local files as a cache."""
    from datetime import datetime, timezone

    root = Path(root).resolve()
    path = Path(filename).resolve()
    if not path.is_relative_to(root / ".godel/sessions") or path.suffix != ".jsonl":
        raise ValueError("Native session must be inside this project session cache.")
    if not path.exists():
        return None  # Pi has not flushed its first assistant response yet.
    content = path.read_text()
    lines = content.splitlines()
    if not lines:
        return None
    header = json.loads(lines[0])
    if header.get("id") != session_id:
        raise ValueError("Native session ID does not match its header.")
    digest = hashlib.sha256(content.encode()).hexdigest()
    event_id = str(uuid.uuid5(uuid.UUID(session_id), path.name + ":" + digest))
    store = project_store(root)
    with store.connection() as db:
        if db.execute("SELECT 1 FROM history_refs WHERE id=?", (event_id,)).fetchone():
            return event_id  # Identical content may have a new filesystem mtime.
    record = dict(
        schemaVersion=1,
        id=event_id,
        at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        projectId=read_project(root)["id"],
        sessionId=session_id,
        type="native_snapshot",
        data={"filename": path.name, "sha256": digest, "content": content},
    )
    save_event(store, record)
    return record["id"]


def restore_native(root):
    """Materialize missing Pi cache files from acknowledged MLflow snapshots."""
    from .traces import read_records

    root = Path(root).resolve()
    store = project_store(root)
    project_id = read_project(root)["id"]
    with store.connection() as db:
        rows = db.execute(
            "SELECT h.sequence,h.id,h.trace_key,h.digest,n.filename FROM native_caches n "
            "JOIN history_refs h ON h.id=n.event_id WHERE n.project_id=?",
            (project_id,),
        ).fetchall()
        refs = [row[:4] for row in rows if not (root / ".godel/sessions" / row[4]).exists()]
    seen, restored = set(), []
    directory = root / ".godel/sessions"
    directory.mkdir(parents=True, exist_ok=True)
    for ref in refs:
        record = read_records(store, [ref])[0]
        data = record["data"]
        name = data["filename"]
        if Path(name).name != name or not name.endswith(".jsonl"):
            raise ValueError("Invalid native session filename in MLflow.")
        if name in seen:
            continue
        seen.add(name)
        path = directory / name
        if path.exists():
            continue  # Never overwrite a newer active session cache.
        if hashlib.sha256(data["content"].encode()).hexdigest() != data["sha256"]:
            raise ValueError("Native session snapshot checksum mismatch.")
        with path.open("x") as stream:
            path.chmod(0o600)
            stream.write(data["content"])
        restored.append(name)
    return restored
