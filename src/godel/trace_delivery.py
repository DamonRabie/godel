"""Background, idempotent OTLP delivery. Import protobuf only in the local service."""

from datetime import datetime
import fcntl
import hashlib
import http.client
import json
import time

from .storage import Store
from .tracking import TrackingError, project_experiment
from .projects import read_project
from .traces import client, invalidate, load_trace, trace_id


def _ns(at):
    return int(datetime.fromisoformat(at).timestamp() * 1_000_000_000)


def _span_id(value):
    return hashlib.sha256(value.encode()).digest()[:8]


def _value(target, value):
    # OTLP carries typed values; MLflow performs its own JSON serialization.
    if isinstance(value, dict):
        for key, item in value.items():
            _value(target.kvlist_value.values.add(key=key).value, item)
    elif isinstance(value, list):
        for item in value:
            _value(target.array_value.values.add(), item)
    elif isinstance(value, bool):
        target.bool_value = value
    elif isinstance(value, int):
        if -(2**63) <= value < 2**63:
            target.int_value = value
        else:
            target.string_value = str(value)
    elif isinstance(value, float):
        target.double_value = value
    elif value is not None:
        target.string_value = str(value)


def _span(key, name, at, attributes, *, id_, parent=True, end=None, error=False):
    from opentelemetry.proto.trace.v1.trace_pb2 import Span

    span = Span(
        trace_id=bytes.fromhex(key.replace("-", "")),
        span_id=_span_id(id_),
        name=name,
        start_time_unix_nano=_ns(at),
        end_time_unix_nano=_ns(end or at),
    )
    if parent:
        span.parent_span_id = _span_id(key + ":root")
    span.status.code = 2 if error else 1
    for key_, value in attributes.items():
        _value(span.attributes.add(key=key_).value, value)
    return span


def deliver(store, refs):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    key = refs[0][2]
    records = [json.loads(row[4]) for row in refs]
    project_id = records[0]["projectId"]
    home = store.path.parent.parent
    http = client(store)
    with store.connection() as db:
        prior = db.execute(
            "SELECT count(*) FROM history_refs WHERE trace_key=? AND delivered=1", (key,)
        ).fetchone()[0]
    projects = (read_project(p.parent) for p in (home / "projects").glob("*/project.json"))
    project = next((p for p in projects if p["id"] == project_id), None)
    if project is None:
        raise ValueError("History project is missing from this workspace.")
    experiment_id = project_experiment(http, store, project)
    if prior:
        invalidate(store, key)  # Another exporter process may have appended spans.
    previous = load_trace(store, key) if prior else {}
    combined = {**previous, **{record["id"]: record for record in records}}
    ordered = sorted(combined.values(), key=lambda r: (r["at"], r["id"]))
    request = ExportTraceServiceRequest()
    spans = request.resource_spans.add().scope_spans.add().spans
    sid = records[0]["sessionId"]
    if not prior:
        try:
            http.request(
                "/api/3.0/mlflow/traces",
                {
                    "trace": {
                        "trace_info": {
                            "trace_id": trace_id(key),
                            "trace_location": {
                                "type": "MLFLOW_EXPERIMENT",
                                "mlflow_experiment": {"experiment_id": experiment_id},
                            },
                            "request_time": ordered[0]["at"],
                            "state": "IN_PROGRESS",
                            "trace_metadata": {"mlflow.trace.session": sid},
                        }
                    }
                },
            )
        except TrackingError as error:
            if "RESOURCE_ALREADY_EXISTS" not in str(error):
                raise
    for record in records:
        data = record["data"]
        data = data if isinstance(data, dict) else {"value": data}
        type_ = record["type"]
        message = data.get("message", {})
        is_model = type_ == "message_end" and message.get("role") == "assistant"
        error = bool(data.get("isError") or message.get("stopReason") in ("error", "aborted"))
        kind = (
            "TOOL"
            if type_ == "tool_end"
            else "LLM"
            if is_model
            else "MEMORY"
            if type_ == "context"
            else "UNKNOWN"
        )
        start = record["at"]
        if type_ == "tool_end":
            candidates = [
                e
                for e in ordered
                if e["type"] == "tool_start"
                and e["data"].get("toolCallId") == data.get("toolCallId")
                and e["at"] <= record["at"]
            ]
            if candidates:
                start = candidates[-1]["at"]
        elif is_model:
            candidates = [
                e for e in ordered if e["type"] == "model_call_start" and e["at"] <= record["at"]
            ]
            if candidates:
                start = candidates[-1]["at"]
        attrs = {
            "mlflow.traceRequestId": trace_id(key),
            "mlflow.spanType": kind,
            "session.id": sid,
            "godel.event": "godel-json:" + json.dumps(record, ensure_ascii=False, allow_nan=False),
            "godel.project_id": project_id,
            "mlflow.spanOutputs": data
            if type_ != "native_snapshot"
            else {"filename": data["filename"], "sha256": data["sha256"]},
        }
        if is_model:
            attrs.update(
                {
                    "mlflow.llm.model": message.get("model"),
                    "mlflow.llm.provider": message.get("provider"),
                }
            )
            # Keep reported usage on the span without MLflow's incremental
            # aggregate counters, which double count on replay in this version.
            attrs["godel.usage"] = message.get("usage", {})
        spans.append(
            _span(
                key,
                type_ if kind != "TOOL" else data.get("toolName", "tool"),
                start,
                attrs,
                id_=record["id"],
                end=record["at"],
                error=error,
            )
        )
    completed = next(
        (
            e
            for e in reversed(ordered)
            if e["type"] in ("agent_end", "session_shutdown", "native_snapshot")
        ),
        None,
    )
    if completed:
        inputs = next((e["data"].get("text") for e in ordered if e["type"] == "input"), None)
        responses = [
            e["data"].get("message", {})
            for e in ordered
            if e["type"] == "message_end"
            and e["data"].get("message", {}).get("role") == "assistant"
        ]
        output = responses[-1].get("content") if responses else None
        interrupted = completed["type"] == "session_shutdown" and inputs is not None
        error = interrupted or bool(
            responses and responses[-1].get("stopReason") in ("error", "aborted")
        )
        spans.append(
            _span(
                key,
                "Godel request" if inputs else "Godel session activity",
                ordered[0]["at"],
                {
                    "mlflow.traceRequestId": trace_id(key),
                    "mlflow.spanType": "AGENT",
                    "session.id": sid,
                    "mlflow.spanInputs": inputs,
                    "mlflow.spanOutputs": output,
                    "godel.project_id": project_id,
                    "godel.interrupted": interrupted,
                },
                id_=key + ":root",
                parent=False,
                end=completed["at"],
                error=error,
            )
        )
    http.request(
        "/v1/traces",
        method="POST",
        body_bytes=request.SerializeToString(),
        raw=True,
        extra_headers={
            "Content-Type": "application/x-protobuf",
            "x-mlflow-experiment-id": experiment_id,
        },
    )
    http.request(
        f"/api/3.0/mlflow/traces/{trace_id(key)}/tags",
        {
            "key": "mlflow.traceName",
            "value": "Godel request"
            if any(e["type"] == "input" for e in ordered)
            else "Godel session activity",
        },
        "PATCH",
    )
    # Read back exact payload hashes before dropping the only pending copy.
    invalidate(store, key)
    saved = load_trace(store, key)
    for _, id_, _, digest, _ in refs:
        actual = json.dumps(saved.get(id_), ensure_ascii=False, allow_nan=False)
        if hashlib.sha256(actual.encode()).hexdigest() != digest:
            raise ValueError(f"MLflow did not preserve event {id_}; pending data retained.")
    with store.connection() as db:
        for _, id_, _, _, _ in refs:
            db.execute("UPDATE history_refs SET delivered=1 WHERE id=?", (id_,))
            db.execute("DELETE FROM pending_history WHERE id=?", (id_,))
            # Delete a legacy body only after verified delivery. Operational IDs remain.
            db.execute("DELETE FROM events WHERE id=?", (id_,))


def flush(home, *, force=False, limit=200):
    store = Store(home)
    with (store.path.parent / "trace-delivery.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"delivered": 0, "busy": True}
        with store.connection() as db:
            rows = db.execute(
                "SELECT h.sequence,h.id,h.trace_key,h.digest,p.body FROM pending_history p "
                "JOIN history_refs h ON h.id=p.id WHERE ? OR p.next_attempt<=? "
                "ORDER BY h.sequence LIMIT ?",
                (force, time.time(), limit),
            ).fetchall()
        groups = {}
        for row in rows:
            groups.setdefault(row[2], []).append(row)
        count = 0
        for refs in groups.values():
            try:
                deliver(store, refs)
                count += len(refs)
            except (
                OSError,
                ValueError,
                KeyError,
                http.client.HTTPException,
                TrackingError,
            ) as error:
                with store.connection() as db:
                    for row in refs:
                        db.execute(
                            "UPDATE pending_history SET attempts=attempts+1,error=?,next_attempt=? + "
                            "min(30, 1 << min(attempts,5)) WHERE id=?",
                            (str(error)[:500], time.time(), row[1]),
                        )
                if isinstance(error, (OSError, http.client.HTTPException)):
                    break
        return {"delivered": count, "busy": False}
