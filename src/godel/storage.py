"""Small durable store; SQLite owns metadata, files own experiment artifacts."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid record ID.") from None
    return value


def text(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must be nonempty text, at most {limit} characters.")
    return value.strip()


def tags(value):
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError("tags must be a list with at most 12 entries.")
    return sorted({text(item, "tag", 60).lower() for item in value})


def read_json(path):
    with Path(path).open() as stream:
        return json.load(stream)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
    try:
        with temporary.open("x") as stream:
            temporary.chmod(0o600)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            import os

            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Store:
    def __init__(self, home):
        self.path = Path(home) / ".godel" / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise ValueError(f"Unsupported state database version: {version}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE, project_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, type TEXT NOT NULL, at TEXT NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session ON events(project_id, session_id, sequence);
                CREATE INDEX IF NOT EXISTS events_type ON events(project_id, type, sequence);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    started_at TEXT NOT NULL, body TEXT NOT NULL, artifact_dir TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id, started_at);
                CREATE TABLE IF NOT EXISTS outbox (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id),
                    revision INTEGER NOT NULL DEFAULT 1,
                    synced_revision INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                    remote_id TEXT, experiment_id TEXT, next_attempt REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS evidence_links (
                    project_id TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                    target_type TEXT NOT NULL, target_id TEXT NOT NULL,
                    PRIMARY KEY(project_id, source_type, source_id, target_type, target_id)
                );
                CREATE TABLE IF NOT EXISTS history_refs (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE, project_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, type TEXT NOT NULL, at TEXT NOT NULL,
                    trace_key TEXT NOT NULL, digest TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS history_session ON history_refs(project_id, session_id, sequence);
                CREATE INDEX IF NOT EXISTS history_trace ON history_refs(trace_key, sequence);
                CREATE TABLE IF NOT EXISTS pending_history (
                    id TEXT PRIMARY KEY REFERENCES history_refs(id), body TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, error TEXT, next_attempt REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS history_sessions (
                    project_id TEXT NOT NULL, session_id TEXT NOT NULL, trace_key TEXT NOT NULL,
                    closed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(project_id, session_id)
                );
                CREATE TABLE IF NOT EXISTS history_projects (
                    project_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS native_caches (
                    project_id TEXT NOT NULL, filename TEXT NOT NULL, event_id TEXT NOT NULL,
                    at TEXT NOT NULL, PRIMARY KEY(project_id, filename)
                );
                PRAGMA user_version = 3;
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def checkpoint(
        self,
        project_id,
        summary,
        next_step,
        blockers,
        evidence_refs=None,
        session_id=None,
        tool_call_id=None,
    ):
        if not isinstance(blockers, list) or len(blockers) > 12:
            raise ValueError("blockers must be a list with at most 12 entries.")
        entry = dict(
            id=str(uuid.uuid4()),
            createdAt=now(),
            summary=text(summary, "summary"),
            next=text(next_step, "next step"),
            blockers=[text(item, "blocker", 1000) for item in blockers],
            evidenceRefs=evidence_refs or [],
            sessionId=session_id,
            toolCallId=tool_call_id,
        )
        with self.connection() as db:
            from .records import validate_refs, _link

            validate_refs(db, project_id, entry["evidenceRefs"])
            db.execute(
                "INSERT INTO checkpoints(project_id, body) VALUES (?, ?)",
                (identifier(project_id), json.dumps(entry)),
            )
            for ref in entry["evidenceRefs"]:
                _link(db, project_id, "checkpoint", entry["id"], ref["type"], ref["id"])
            _link(db, project_id, "checkpoint", entry["id"], "session", session_id)
            _link(db, project_id, "checkpoint", entry["id"], "tool_call", tool_call_id)
        return entry

    def latest_checkpoint(self, project_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT body FROM checkpoints WHERE project_id=? ORDER BY sequence DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def propose(
        self,
        project_id,
        lesson,
        evidence,
        scope="project",
        lesson_tags=None,
        evidence_refs=None,
        session_id=None,
        tool_call_id=None,
    ):
        if scope not in ("project", "shared"):
            raise ValueError("Lesson scope must be project or shared.")
        applicable_tags = tags(lesson_tags or [])
        if scope == "shared" and not applicable_tags:
            raise ValueError("Shared lessons require at least one applicability tag.")
        entry = dict(
            id=str(uuid.uuid4()),
            projectId=identifier(project_id),
            createdAt=now(),
            lesson=text(lesson, "lesson", 1200),
            evidence=text(evidence, "evidence", 2000),
            scope=scope,
            tags=applicable_tags,
            status="proposed",
            history=[],
            evidenceRefs=evidence_refs or [],
            sessionId=session_id,
            toolCallId=tool_call_id,
        )
        with self.connection() as db:
            from .records import validate_refs, _link

            validate_refs(db, project_id, entry["evidenceRefs"])
            db.execute("INSERT INTO lessons VALUES (?, ?)", (entry["id"], json.dumps(entry)))
            for ref in entry["evidenceRefs"]:
                _link(db, project_id, "lesson", entry["id"], ref["type"], ref["id"])
            _link(db, project_id, "lesson", entry["id"], "session", session_id)
            _link(db, project_id, "lesson", entry["id"], "tool_call", tool_call_id)
        return entry

    def lessons(self):
        with self.connection() as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT body FROM lessons ORDER BY rowid DESC")
            ]

    def review(self, lesson_id, action, note):
        identifier(lesson_id)
        if action not in ("accept", "retire"):
            raise ValueError("Review action must be accept or retire.")
        note = text(note, "review note", 2000)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM lessons WHERE id=?", (lesson_id,)).fetchone()
            if not row:
                raise ValueError("Lesson does not exist.")
            entry = json.loads(row[0])
            entry["status"] = "active" if action == "accept" else "retired"
            entry["history"].append(dict(at=now(), action=action, note=note))
            db.execute("UPDATE lessons SET body=? WHERE id=?", (json.dumps(entry), lesson_id))
        return entry

    def relevant(self, project, query, max_chars=4000):
        words = set(query.lower().split())
        eligible = [
            entry
            for entry in self.lessons()
            if entry["status"] == "active"
            and (
                (entry["scope"] == "project" and entry["projectId"] == project["id"])
                or (entry["scope"] == "shared" and set(entry["tags"]) & set(project["tags"]))
            )
        ]
        eligible.sort(
            key=lambda entry: (
                len(words & set(entry["lesson"].lower().split()))
                + 2 * (entry["projectId"] == project["id"]),
                entry["createdAt"],
            ),
            reverse=True,
        )
        selected, used = [], 0
        for entry in eligible:
            item = {key: entry[key] for key in ("id", "lesson", "evidence")}
            item["evidenceRefs"] = entry.get("evidenceRefs", [])
            size = len(json.dumps(item))
            if used + size <= max_chars:
                selected.append(item)
                used += size
            if len(selected) == 5:
                break
        return selected
