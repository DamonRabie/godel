"""Queryable local evidence. MLflow is a projection of this durable record."""

import json
import hashlib
from pathlib import Path

from .storage import Store, identifier


def get_run(root, run_id):
    from .projects import read_project
    from .storage import read_json

    project_id = read_project(root)["id"]
    with project_store(root).connection() as db:
        row = db.execute(
            "SELECT body FROM runs WHERE id=? AND project_id=?", (identifier(run_id), project_id)
        ).fetchone()
    if row:
        return json.loads(row[0])
    run = read_json(Path(root) / ".godel/runs" / run_id / "run.json")
    if run.get("id") != run_id or run.get("projectId") != project_id:
        raise ValueError("Run identity does not match its project record.")
    return run


def project_store(root):
    root = Path(root).resolve()
    if root.parent.name != "projects":
        raise ValueError("Recorded projects must live under the workspace projects/ directory.")
    return Store(root.parent.parent)


def _link(db, project_id, source_type, source_id, target_type, target_id):
    if target_id:
        db.execute(
            "INSERT OR IGNORE INTO evidence_links VALUES (?, ?, ?, ?, ?)",
            (project_id, source_type, source_id, target_type, target_id),
        )


def validate_refs(db, project_id, refs):
    if not isinstance(refs, list) or len(refs) > 32:
        raise ValueError("evidenceRefs must contain at most 32 run or event references.")
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("type") not in ("run", "event"):
            raise ValueError("Evidence references need type (run or event) and id.")
        table = "runs" if ref["type"] == "run" else "history_refs"
        row = db.execute(
            f"SELECT project_id FROM {table} WHERE id=?", (identifier(ref.get("id")),)
        ).fetchone()
        if not row or row[0] != project_id:
            raise ValueError("Evidence reference does not exist in this project.")


def save_event(store, record):
    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        refs = record["data"].get("evidenceRefs", []) if isinstance(record["data"], dict) else []
        # Only explicit decisions carry validated evidence references. Other events
        # retain arbitrary Pi payloads, including older journals.
        if record["type"] == "decision":
            validate_refs(db, record["projectId"], refs)
        existing = db.execute(
            "SELECT digest FROM history_refs WHERE id=?", (record["id"],)
        ).fetchone()
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        if existing:
            if existing[0] != digest:
                raise ValueError("An event ID cannot be reused with different content.")
            return False
        session = db.execute(
            "SELECT trace_key, closed FROM history_sessions WHERE project_id=? AND session_id=?",
            (record["projectId"], record["sessionId"]),
        ).fetchone()
        trace_key = (
            record["id"]
            if not session
            or session[1]
            or record["type"] in ("input", "session_start", "native_snapshot")
            else session[0]
        )
        closed = record["type"] in ("agent_end", "session_shutdown")
        if record["type"] != "native_snapshot":
            db.execute(
                "INSERT INTO history_sessions VALUES (?, ?, ?, ?) ON CONFLICT(project_id, session_id) "
                "DO UPDATE SET trace_key=excluded.trace_key, closed=excluded.closed",
                (record["projectId"], record["sessionId"], trace_key, closed),
            )
        inserted = db.execute(
            "INSERT INTO history_refs(id, project_id, session_id, type, at, trace_key, digest) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record["id"],
                record["projectId"],
                record["sessionId"],
                record["type"],
                record["at"],
                trace_key,
                digest,
            ),
        ).rowcount
        db.execute("INSERT INTO pending_history(id, body) VALUES (?, ?)", (record["id"], encoded))
        if record["type"] == "native_snapshot":
            db.execute(
                "INSERT INTO native_caches VALUES (?, ?, ?, ?) ON CONFLICT(project_id,filename) "
                "DO UPDATE SET event_id=excluded.event_id,at=excluded.at WHERE excluded.at>=native_caches.at",
                (record["projectId"], record["data"]["filename"], record["id"], record["at"]),
            )
        if inserted:
            _link(db, record["projectId"], "event", record["id"], "session", record["sessionId"])
            data = record["data"]
            if isinstance(data, dict):
                _link(
                    db,
                    record["projectId"],
                    "event",
                    record["id"],
                    "tool_call",
                    data.get("toolCallId"),
                )
                if record["type"] == "context":
                    for lesson in data.get("context", {}).get("lessons", []):
                        _link(
                            db, record["projectId"], "event", record["id"], "lesson", lesson["id"]
                        )
                if record["type"] == "session_start":
                    _link(
                        db,
                        record["projectId"],
                        "session",
                        record["sessionId"],
                        "pi_session_file",
                        data.get("parentSessionFile"),
                    )
                if record["type"] == "decision":
                    for ref in refs:
                        _link(
                            db, record["projectId"], "event", record["id"], ref["type"], ref["id"]
                        )
        return bool(inserted)


def save_run(root, record):
    store = project_store(root)
    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
    artifact_dir = str(Path(root).resolve() / ".godel/runs" / identifier(record["id"]))
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT body FROM runs WHERE id=?", (record["id"],)).fetchone()
        if old and old[0] == encoded:
            return
        db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (
                record["id"],
                record["projectId"],
                record["sessionId"],
                record["startedAt"],
                encoded,
                artifact_dir,
            ),
        )
        db.execute(
            "INSERT INTO outbox(run_id) VALUES (?) ON CONFLICT(run_id) DO UPDATE "
            "SET revision=revision+1, next_attempt=0",
            (record["id"],),
        )
        _link(db, record["projectId"], "run", record["id"], "session", record["sessionId"])
        _link(
            db,
            record["projectId"],
            "run",
            record["id"],
            "run",
            record["request"].get("parentRunId"),
        )
        _link(db, record["projectId"], "run", record["id"], "tool_call", record.get("toolCallId"))


def query_history(store, project_id, **kwargs):
    from .traces import query_history as query

    return query(store, project_id, **kwargs)


def evidence(store, project_id, record_id):
    """Direct links, in both directions; consumers can traverse deliberately."""
    with store.connection() as db:
        links = [
            dict(sourceType=row[0], sourceId=row[1], targetType=row[2], targetId=row[3])
            for row in db.execute(
                "SELECT source_type, source_id, target_type, target_id FROM evidence_links "
                "WHERE project_id=? AND (source_id=? OR target_id=?) LIMIT 101",
                (project_id, record_id, record_id),
            )
        ]
        row = db.execute(
            "SELECT body FROM runs WHERE project_id=? AND id=?", (project_id, record_id)
        ).fetchone()
        lesson_row = db.execute("SELECT body FROM lessons WHERE id=?", (record_id,)).fetchone()
        lesson = json.loads(lesson_row[0]) if lesson_row else None
        if lesson and lesson["projectId"] != project_id:
            lesson = None
        checkpoint = next(
            (
                item
                for (body,) in db.execute(
                    "SELECT body FROM checkpoints WHERE project_id=?", (project_id,)
                )
                if (item := json.loads(body))["id"] == record_id
            ),
            None,
        )
    return {
        "id": record_id,
        "run": json.loads(row[0]) if row else None,
        "lesson": lesson,
        "checkpoint": checkpoint,
        "links": links[:100],
        "linksTruncated": len(links) > 100,
        **query_history(store, project_id, evidence_id=record_id),
    }
