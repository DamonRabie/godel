"""MLflow is the authoritative event history; SQLite retains IDs and pending delivery only."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import re
import threading
from urllib.parse import urlencode

from .storage import identifier
from .tracking import Client, TrackingError, settings

_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_BYTES = 32 * 1024 * 1024


def trace_id(key):
    return "tr-" + identifier(key).replace("-", "")


def client(store):
    return Client(settings(store.path.parent.parent)["port"])


def invalidate(store, key):
    with _CACHE_LOCK:
        _CACHE.pop((str(store.path), key), None)


def load_trace(store, key):
    cache_key = (str(store.path), key)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached:
            _CACHE.move_to_end(cache_key)
            return cached[0]
    response = client(store).request(
        "/api/3.0/mlflow/traces/get?"
        + urlencode({"trace_id": trace_id(key), "allow_partial": "true"})
    )
    spans = response["trace"].get("spans", [])
    records = {}
    for span in spans:
        raw = next(
            (
                item["value"].get("string_value", item["value"].get("stringValue"))
                for item in span.get("attributes", [])
                if item["key"] == "godel.event"
            ),
            None,
        )
        if raw:
            record = json.loads(raw.removeprefix("godel-json:"))
            records[record["id"]] = record
    size = len(json.dumps(records))
    with _CACHE_LOCK:
        _CACHE[cache_key] = (records, size)
        while _CACHE and sum(entry[1] for entry in _CACHE.values()) > _CACHE_BYTES:
            _CACHE.popitem(last=False)
    return records


def read_records(store, refs):
    """Read acknowledged payloads from MLflow; unacknowledged payloads from the queue."""
    with store.connection() as db:
        ids = [row[1] for row in refs]
        pending = {
            id_: json.loads(body)
            for id_, body in db.execute(
                "SELECT id, body FROM pending_history WHERE id IN ("
                + ",".join("?" for _ in ids)
                + ")",
                ids,
            )
        }
    keys = {row[2] for row in refs if row[1] not in pending}
    with ThreadPoolExecutor(max_workers=4) as pool:
        remote = list(pool.map(lambda key: load_trace(store, key), sorted(keys)))
    records = {id_: record for batch in remote for id_, record in batch.items()}
    records.update(pending)
    result = []
    for sequence, id_, key, digest in refs:
        record = records.get(id_)
        if not record:
            # A long-running process may have cached an earlier partial trace.
            invalidate(store, key)
            record = load_trace(store, key).get(id_)
        if not record:
            raise ValueError(
                f"History event {id_} is missing from its MLflow trace; do not infer its contents."
            )
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
        if hashlib.sha256(encoded.encode()).hexdigest() != digest:
            raise ValueError(f"History event {id_} failed its integrity check.")
        result.append(
            dict(record, sequence=sequence, traceId=trace_id(key), pending=id_ in pending)
        )
    return result


def _literal(value):
    # Only IDs and a safe ASCII search fragment enter these filters.
    return "'" + str(value).replace("'", "''") + "'"


def _contains(value, query):
    if isinstance(value, dict):
        return any(
            query in str(key).lower() or _contains(item, query) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains(item, query) for item in value)
    return query in str(value).lower()


def query_history(
    store,
    project_id,
    *,
    session_id=None,
    event_type=None,
    query=None,
    after=0,
    limit=30,
    evidence_id=None,
):
    if type(limit) is not int or not 1 <= limit <= 100 or type(after) is not int or after < 0:
        raise ValueError("History requires limit 1–100 and a nonnegative after cursor.")
    if query is not None and (not isinstance(query, str) or len(query) > 4000):
        raise ValueError("History query must be at most 4000 characters.")
    clauses, values = ["project_id=?", "sequence>?"], [project_id, after]
    for column, value in (("session_id", session_id), ("type", event_type)):
        if value:
            clauses.append(f"{column}=?")
            values.append(value)
    if not event_type:
        clauses.append("type!='native_snapshot'")
    if evidence_id:
        clauses.append(
            "(id=? OR id IN (SELECT source_id FROM evidence_links WHERE project_id=? "
            "AND source_type='event' AND target_id=?))"
        )
        values.extend([evidence_id, project_id, evidence_id])
    with store.connection() as db:
        refs = db.execute(
            "SELECT sequence,id,trace_key,digest FROM history_refs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY sequence",
            values,
        ).fetchall()
        experiment = db.execute(
            "SELECT experiment_id FROM history_projects WHERE project_id=?", (project_id,)
        ).fetchone()
        pending_keys = {
            row[0]
            for row in db.execute(
                "SELECT DISTINCT h.trace_key FROM history_refs h "
                "JOIN pending_history p ON p.id=h.id WHERE h.project_id=?",
                (project_id,),
            )
        }
    try:
        # MLflow's full-text search narrows traces on the server. Payloads stay there.
        # MLflow searches serialized span JSON. Escaping and Unicode rendering
        # differ from event text, so narrow with a safe fragment, then match the
        # exact original query below. Queries without one use bounded reads.
        fragment = max(re.findall(r"[A-Za-z0-9 _-]+", query or ""), key=len, default="").strip()
        if fragment and experiment:
            filter_ = f"`text` ILIKE {_literal('%' + fragment + '%')}"
            if session_id:
                filter_ += f" AND metadata.`mlflow.trace.session` = {_literal(session_id)}"
            matching, token = set(), None
            while True:
                payload = {
                    "locations": [{"mlflow_experiment": {"experiment_id": experiment[0]}}],
                    "filter": filter_,
                    "max_results": 100,
                }
                if token:
                    payload["page_token"] = token
                response = client(store).request("/api/3.0/mlflow/traces/search", payload)
                matching.update(
                    item["trace_id"].removeprefix("tr-") for item in response.get("traces", [])
                )
                token = response.get("next_page_token")
                if not token:
                    break
            refs = [r for r in refs if r[2] in pending_keys or r[2].replace("-", "") in matching]
        events = []
        for offset in range(0, len(refs), 40):
            for record in read_records(store, refs[offset : offset + 40]):
                if query and not _contains(record, query.lower()):
                    continue
                events.append(record)
                if len(events) > limit:
                    break
            if len(events) > limit:
                break
        next_cursor = events[limit - 1]["sequence"] if len(events) > limit else None
        for record in events[:limit]:
            data = json.dumps(record["data"], ensure_ascii=False)
            if len(data) > 6000:
                record["data"] = {
                    "preview": data[:6000],
                    "truncated": True,
                    "readFull": "Use godel_history_event with this event ID and offset.",
                }
        return {
            "historyStore": "mlflow",
            "available": True,
            "events": events[:limit],
            "nextCursor": next_cursor,
        }
    except (OSError, http.client.HTTPException, TrackingError) as error:
        return {
            "historyStore": "mlflow",
            "available": False,
            "events": [],
            "nextCursor": after,
            "error": f"MLflow history is unavailable ({type(error).__name__}). Retry after tracking start; this is not an empty history.",
        }


def read_event(store, project_id, event_id, offset=0, limit=6000):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20000:
        raise ValueError("Event reads require a nonnegative offset and limit 1–20000.")
    with store.connection() as db:
        refs = db.execute(
            "SELECT sequence,id,trace_key,digest FROM history_refs WHERE id=? AND project_id=?",
            (identifier(event_id), project_id),
        ).fetchall()
    if not refs:
        raise ValueError("Event does not exist in this project.")
    record = read_records(store, refs)[0]
    data = json.dumps(record["data"], ensure_ascii=False)
    return {
        "eventId": event_id,
        "traceId": record["traceId"],
        "text": data[offset : offset + limit],
        "nextOffset": offset + limit if offset + limit < len(data) else None,
        "totalCharacters": len(data),
    }


def sessions(store, project_id):
    with store.connection() as db:
        rows = db.execute(
            "SELECT session_id,count(*),min(at),max(at),sum(delivered=0) FROM history_refs "
            "WHERE project_id=? GROUP BY session_id ORDER BY max(at) DESC",
            (project_id,),
        ).fetchall()
        experiment = db.execute(
            "SELECT experiment_id FROM history_projects WHERE project_id=?", (project_id,)
        ).fetchone()
    url = settings(store.path.parent.parent)["url"]
    return {
        "sessions": [
            dict(sessionId=r[0], events=r[1], startedAt=r[2], lastEventAt=r[3], pending=r[4])
            for r in rows
        ],
        "url": f"{url}/#/experiments/{experiment[0]}/chat-sessions" if experiment else url,
    }
