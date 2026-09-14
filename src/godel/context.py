from pathlib import Path

from .experiments import comparable, list_runs
from .projects import read_project
from .review import candidate_count, review_run
from .runtime import bundled_skills
from .storage import Store
from .tracking import status as tracking_status


def integrations(home):
    home = Path(home)
    ready = all(
        (home / path).is_file()
        for path in (
            "bin/kaggle.py",
            ".godel/tools/kaggle/bin/python",
            ".godel/kaggle/access_token",
        )
    )
    return {
        "kaggle": {
            "configured": ready,
            "command": ["python3", str(home / "bin/kaggle.py")],
            "guide": str(home / "docs/kaggle.md"),
            "usage": "Use this CLI wrapper for Kaggle access and downloads. It loads private "
            "credentials for its child process. Direct "
            "kagglehub calls and bare kaggle commands do not use this configuration. "
            "Do not read private configuration into context. Configuration presence "
            "does not prove live access. Test this wrapper before diagnosing access; "
            "a generic HTTP 403 alone does not prove rules were not accepted. "
            "Remote training must also be recorded: read the guide's agent-owned "
            "tracking workflow, register each job/version with godel_remote_run, "
            "then collect and import its results into that same run. The guide "
            "includes an API fallback for sessions without the new tool.",
        }
    }


def _bounded_document(path, limit):
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "text": "", "missing": True, "truncated": False}
    if path.is_symlink() or not path.is_file():
        return {
            "path": str(path),
            "text": "",
            "missing": False,
            "error": "Expected a regular document.",
        }
    with path.open() as stream:
        content = stream.read(limit + 1)
    return {
        "path": str(path),
        "text": content[:limit],
        "missing": False,
        "truncated": len(content) > limit,
    }


def _metric_summary(run):
    values = run.get("metrics", {})
    primary = run["evaluation"]["metric"]
    names = [primary] + [name for name in values if name != primary]
    return {name: values[name] for name in names[:16] if name in values}


def context(home, root, query=""):
    project = read_project(root)
    store = Store(home)
    runs = list_runs(root)
    candidates = [run for run in runs if comparable(run, project["evaluation"])]
    best = None
    if candidates:
        metric = project["evaluation"]["metric"]
        candidates.sort(
            key=lambda run: run["metrics"][metric],
            reverse=project["evaluation"]["direction"] == "maximize",
        )
        for candidate in candidates:
            review = review_run(root, candidate)
            if review["status"] != "inconsistent":
                best = {key: candidate[key] for key in ("id", "metrics", "evaluation")}
                best["metrics"] = _metric_summary(candidate)
                best["interpretation"] = (
                    "Highest recorded comparable score; not a confirmed generalization improvement or promotion decision."
                )
                best["evidence"] = {
                    key: review[key]
                    for key in ("status", "candidateEvaluations", "selectedCandidate", "splitHash")
                    if key in review
                }
                best["warnings"] = review["warnings"][:8]
                break
    brief = _bounded_document(Path(root) / "brief.md", 6000)
    same_evaluation = [run for run in runs if run["evaluation"] == project["evaluation"]]
    same_dataset = [
        run for run in runs if run["evaluation"]["datasetId"] == project["evaluation"]["datasetId"]
    ]
    development = dict(
        guide=_bounded_document(Path(home) / "agent/model-development.md", 2500),
        skills=[dict(name=path.parent.name, path=str(path)) for path in bundled_skills(home)],
        protocol=_bounded_document(Path(root) / "protocol.md", 6000),
        recordedAttempts=len(runs),
        candidateEvaluationsOnCurrentEvaluation=sum(
            candidate_count(run) for run in same_evaluation
        ),
        candidateEvaluationsOnCurrentDataset=sum(candidate_count(run) for run in same_dataset),
        candidateEvaluationsProjectTotal=sum(candidate_count(run) for run in runs),
        accounting="Counts recorded candidate evaluations, including repeats and declared failed attempts; legacy records may undercount. Not unique models or fitted folds. Dataset exposure spans split/metric changes but matches declared datasetId only; renamed/overlapping data require protocol review. These counts are exposure, not remaining authorization.",
        nextReview="Read protocol.md and the selected run's evidence before further tuning. Repeated use of one evaluation requires addressing selection bias; do not postpone a promised diagnostic stage.",
        reviewCommand=[
            "python3",
            str(Path(home) / "bin/godel.py"),
            "review",
            project["name"],
            "<run-id>",
        ],
    )
    tracking = tracking_status(home, project["id"])
    return dict(
        project=project,
        brief=brief["text"],
        briefTruncated=brief.get("truncated", False),
        tracking={key: tracking[key] for key in ("url", "pending", "synced")},
        modelDevelopment=development,
        integrations=integrations(home),
        checkpoint=store.latest_checkpoint(project["id"]),
        lessons=store.relevant(project, query),
        bestMeasuredRun=best,
        recentRuns=[
            dict(
                {key: run[key] for key in ("id", "status", "measurement", "startedAt")},
                hypothesis=run["request"]["hypothesis"][:600],
                metrics=_metric_summary(run),
                metricsTruncated=len(run.get("metrics", {})) > 16,
                candidateEvaluations=candidate_count(run),
                remote=run.get("remote"),
                sessionId=run.get("sessionId"),
                evaluation=run["evaluation"],
                parentRunId=run["request"].get("parentRunId"),
            )
            for run in runs[:5]
        ],
    )


def display_context(value):
    project, checkpoint = value["project"], value["checkpoint"]
    lines = [
        f"## {project['name']}",
        project["goal"],
        f"Budget: {project['maxRunSeconds']}s/run, {project['maxRunsPerSession']} runs/session.",
        f"Next: {checkpoint['next'] if checkpoint else 'Clarify the brief and establish a baseline.'}",
    ]
    if checkpoint:
        lines.extend(
            [
                f"Progress: {checkpoint['summary']}",
                f"Blockers: {', '.join(checkpoint['blockers']) or 'none recorded'}",
            ]
        )
    best = value["bestMeasuredRun"]
    if best:
        metric = best["evaluation"]["metric"]
        lines.append(
            f"Highest recorded {metric}: {best['metrics'][metric]:.6g}\nRun: {best['id']}\nThis ranking does not confirm generalization or promotion."
        )
        lines.append(
            f"Dataset: {best['evaluation']['datasetId']}\nSplit: {best['evaluation']['splitId']}"
        )
    else:
        lines.append("No comparable valid measurement yet.")
    lines.append(f"Active lessons in context: {len(value['lessons'])}")
    lines.append(
        f"Candidate evaluations on current evaluation: {value['modelDevelopment']['candidateEvaluationsOnCurrentEvaluation']} (includes repeats).\nML protocol: protocol.md · Evidence review: godel review <project> <run-id>"
    )
    lines.append(
        f"Recorded exposure: {value['modelDevelopment']['candidateEvaluationsOnCurrentDataset']} evaluations on this declared dataset across splits; {value['modelDevelopment']['candidateEvaluationsProjectTotal']} project-wide. These are not remaining budget counts."
    )
    lines.append(
        f"MLflow: {value['tracking']['url']} · {value['tracking']['pending']} pending exports. Use /tracking for run links."
    )
    lines.append(
        "Decisions and evidence: godel_history / godel_evidence · Project brief: brief.md · Local run artifacts: .godel/runs/"
    )
    return "\n\n".join(lines)
