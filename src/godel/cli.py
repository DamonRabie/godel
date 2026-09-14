import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from .context import context, display_context
from .experiments import list_runs, run_experiment
from .history import append_event, import_history, list_history, provenance
from .records import query_history, evidence
from . import tracking
from .projects import init_project, project_path, read_project
from .runtime import launch_spec
from .review import review_experiment
from .storage import Store, atomic_json


HOME = Path(__file__).resolve().parents[2]


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def api(home, root, action, payload):
    root = Path(root).resolve()
    if not root.is_relative_to(Path(home).resolve()):
        raise ValueError("Project is outside the Godel workspace.")
    project = read_project(root)
    store = Store(home)
    if action == "context":
        return context(home, root, payload.get("query", ""))
    if action == "status":
        return display_context(context(home, root))
    if action == "history":
        return list_history(root)
    if action == "history_search":
        return query_history(
            store,
            project["id"],
            session_id=payload.get("sessionId"),
            event_type=payload.get("eventType"),
            query=payload.get("query"),
            after=payload.get("after", 0),
            limit=payload.get("limit", 30),
        )
    if action == "history_event":
        from .traces import read_event

        return read_event(
            store,
            project["id"],
            payload["id"],
            payload.get("offset", 0),
            payload.get("limit", 6000),
        )
    if action == "evidence":
        return evidence(store, project["id"], payload["id"])
    if action == "tracking":
        return tracking.status(home, project["id"])
    if action == "decision":
        from .storage import text

        data = dict(
            summary=text(payload["summary"], "decision"),
            rationale=text(payload["rationale"], "rationale"),
            evidenceRefs=payload.get("evidenceRefs", []),
            toolCallId=payload.get("toolCallId"),
        )
        return append_event(root, payload["sessionId"], "decision", data)
    if action == "event":
        if payload["type"] in (
            "agent_end",
            "session_shutdown",
            "compaction",
            "branch",
        ) and payload.get("sessionFile"):
            from .history import snapshot_native

            snapshot_native(root, payload["sessionId"], payload["sessionFile"])
        data = payload["data"]
        if payload["type"] == "session_start":
            data = {**data, "runtimeHashes": provenance(home)}
        return append_event(root, payload["sessionId"], payload["type"], data)
    if action == "checkpoint":
        return store.checkpoint(
            project["id"],
            payload["summary"],
            payload["next"],
            payload["blockers"],
            payload.get("evidenceRefs"),
            payload.get("sessionId"),
            payload.get("toolCallId"),
        )
    if action == "run":
        return run_experiment(
            root,
            payload["request"],
            payload["sessionId"],
            payload.get("model"),
            payload.get("toolCallId"),
        )
    if action == "remote_run":
        from .remote import remote_run

        return remote_run(
            root,
            payload["request"],
            payload["sessionId"],
            payload.get("model"),
            payload.get("toolCallId"),
        )
    if action == "review":
        return review_experiment(root, payload["runId"], payload.get("baselineRunId"))
    if action == "propose":
        return store.propose(
            project["id"],
            payload["lesson"],
            payload["evidence"],
            payload["scope"],
            payload["tags"],
            payload.get("evidenceRefs"),
            payload.get("sessionId"),
            payload.get("toolCallId"),
        )
    if action == "lessons":
        return [
            item
            for item in store.lessons()
            if item["projectId"] == project["id"] or item["scope"] == "shared"
        ]
    if action in ("accept", "retire"):
        return store.review(payload["id"], action, payload["note"])
    if action == "teach":
        lesson = store.propose(
            project["id"],
            payload["lesson"],
            payload["evidence"],
            "project",
            project["tags"],
            session_id=payload.get("sessionId"),
        )
        return store.review(lesson["id"], "accept", "Explicit user correction through /teach.")
    if action == "runs":
        return list_runs(root)
    raise ValueError(f"Unknown API action: {action}")


def parser():
    result = argparse.ArgumentParser(
        description="Godel — a self-contained ML workspace powered by Pi"
    )
    commands = result.add_subparsers(dest="action", required=True)
    init = commands.add_parser("init", help="Create an independent Python ML project repository")
    init.add_argument("name")
    init.add_argument("--goal", default="Define the ML objective with the user.")
    chat = commands.add_parser("chat", help="Open the project in Godel's isolated Pi configuration")
    chat.add_argument("name")
    chat.add_argument("--continue", dest="continue_session", action="store_true")
    chat.add_argument("--model")
    chat.add_argument("--provider")
    chat.add_argument(
        "--offline",
        action="store_true",
        help="Disable Pi startup network calls; inference still needs a provider",
    )
    for command in ("status", "runs"):
        commands.add_parser(command).add_argument("name")
    history = commands.add_parser(
        "history", help="Locate saved conversation journals and native Pi sessions"
    )
    history.add_argument("name", nargs="?", help="Omit to list all projects")
    history.add_argument("--query", help="Search indexed events")
    history.add_argument("--session")
    history.add_argument("--type", dest="event_type")
    history.add_argument("--after", type=int, default=0)
    history.add_argument("--limit", type=int, default=30)
    evidence_parser = commands.add_parser(
        "evidence", help="Inspect a record and its evidence links"
    )
    evidence_parser.add_argument("name")
    evidence_parser.add_argument("id")
    tracker = commands.add_parser(
        "tracking", help="Manage workspace-local MLflow and retry exports"
    )
    tracker.add_argument(
        "operation",
        choices=("start", "stop", "serve", "status", "sync", "import", "migrate-history"),
    )
    run = commands.add_parser("run", help="Run a recorded experiment from a JSON request file")
    run.add_argument("name")
    run.add_argument("request_file", type=Path)
    review = commands.add_parser("review", help="Review experiment evidence without running models")
    review.add_argument("name")
    review.add_argument("run_id")
    review.add_argument("--baseline", dest="baseline_id")
    lessons = commands.add_parser("lessons", help="Inspect or review stored lessons")
    lessons.add_argument(
        "operation", choices=("list", "accept", "retire"), default="list", nargs="?"
    )
    lessons.add_argument("id", nargs="?")
    lessons.add_argument("--note", default="Reviewed by the user through the Godel CLI.")
    commands.add_parser(
        "doctor", help="Check local installation without model calls or global configuration reads"
    )
    commands.add_parser("demo", help="Run a small synthetic regression experiment without an LLM")
    bridge = commands.add_parser("api", help=argparse.SUPPRESS)
    bridge.add_argument("operation")
    bridge.add_argument("--project", required=True, type=Path)
    bridge.add_argument("--payload", help="JSON payload; defaults to JSON on stdin")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "init":
            root, _ = init_project(HOME, args.name, args.goal)
            print(f"Created {root}\nStart: python3 bin/godel.py chat {args.name}")
        elif args.action == "chat":
            root = project_path(HOME, args.name)
            read_project(root)
            tracking.start(HOME)
            from .history import restore_native

            restore_native(root)
            extra = []
            if args.continue_session:
                extra.append("--continue")
            for option in ("model", "provider"):
                if getattr(args, option):
                    extra.extend([f"--{option}", getattr(args, option)])
            if args.offline:
                extra.append("--offline")
            command, env = launch_spec(HOME, root, extra)
            os.chdir(root)
            os.execvpe(command[0], command, env)
        elif args.action == "status":
            print(display_context(context(HOME, project_path(HOME, args.name))))
        elif args.action == "runs":
            emit(list_runs(project_path(HOME, args.name)))
        elif args.action == "review":
            emit(review_experiment(project_path(HOME, args.name), args.run_id, args.baseline_id))
        elif args.action == "history":
            roots = (
                [project_path(HOME, args.name)]
                if args.name
                else sorted(path.parent for path in (HOME / "projects").glob("*/project.json"))
            )
            if args.query is not None or args.session or args.event_type:
                emit(
                    [
                        {
                            "project": root.name,
                            **query_history(
                                Store(HOME),
                                read_project(root)["id"],
                                query=args.query,
                                session_id=args.session,
                                event_type=args.event_type,
                                after=args.after,
                                limit=args.limit,
                            ),
                        }
                        for root in roots
                    ]
                )
            else:
                emit([list_history(root) for root in roots])
        elif args.action == "evidence":
            emit(evidence(Store(HOME), read_project(project_path(HOME, args.name))["id"], args.id))
        elif args.action == "tracking":
            if args.operation == "migrate-history":
                return subprocess.call(
                    [
                        str(HOME / ".venv/bin/python"),
                        "-m",
                        "godel.migrate_history",
                        "--home",
                        str(HOME),
                    ]
                )
            elif args.operation == "start":
                emit(tracking.start(HOME))
            elif args.operation == "stop":
                emit(tracking.stop(HOME))
            elif args.operation == "serve":
                tracking.serve(HOME)
            elif args.operation == "import":
                emit(import_history(HOME))
            elif args.operation == "sync":
                emit({**tracking.sync(HOME, force=True), **tracking.status(HOME)})
            else:
                emit(tracking.status(HOME))
        elif args.action == "run":
            with args.request_file.open() as stream:
                request = json.load(stream)
            record = run_experiment(project_path(HOME, args.name), request, str(uuid.uuid4()))
            emit(record)
            return (
                0
                if record["status"] == "succeeded"
                and record["measurement"] == "valid"
                and record["evidenceReview"]["status"] != "inconsistent"
                else 1
            )
        elif args.action == "lessons":
            store = Store(HOME)
            emit(
                store.lessons()
                if args.operation == "list"
                else store.review(args.id, args.operation, args.note)
            )
        elif args.action == "api":
            raw = args.payload if args.payload is not None else sys.stdin.read()
            payload = json.loads(raw or "{}")
            if not isinstance(payload, dict):
                raise ValueError("API payload must be a JSON object.")
            emit(api(HOME, args.project, args.operation, payload))
        elif args.action == "doctor":
            checks = {
                "python": sys.version.split()[0],
                "git": shutil.which("git"),
                "node": shutil.which("node"),
                "piInstalled": (HOME / "node_modules/.bin/pi").exists(),
                "adapterBuilt": (HOME / "dist/pi/extension.js").exists(),
                "workspace": str(HOME),
                "piConfig": str(HOME / ".godel/pi"),
            }
            emit(checks)
            return 0 if all(checks.values()) else 1
        elif args.action == "demo":
            name = f"demo-{uuid.uuid4().hex[:8]}"
            root, project = init_project(
                HOME, name, "Fit a linear regression and compare with a mean baseline."
            )
            shutil.copyfile(HOME / "examples/tiny_regression.py", root / "experiments/baseline.py")
            project.update(
                tags=["regression"],
                evaluation={
                    "datasetId": "synthetic-linear-v1-seed-17",
                    "splitId": "first-80-train-last-20-validation",
                    "metric": "mse",
                    "direction": "minimize",
                },
            )
            atomic_json(root / "project.json", project)
            record = run_experiment(
                root,
                {
                    "hypothesis": "A fitted line beats a training-mean baseline.",
                    "command": [sys.executable, "experiments/baseline.py"],
                    "sources": ["experiments/baseline.py"],
                    "timeoutSeconds": 10,
                    "candidateCount": 2,
                },
                "demo",
            )
            emit({"project": name, "run": record})
            return 0 if record["status"] == "succeeded" and record["measurement"] == "valid" else 1
        return 0
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"godel: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
