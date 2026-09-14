"""Read-only checks of experiment evidence. These do not certify ML validity."""

import hashlib
import math
from pathlib import Path
import statistics

from .storage import identifier, read_json


def _artifact(directory, name, limit=262144):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("Artifact must be a run-relative path.")
    path = directory / name
    if (
        any(part in ("..", "sources") for part in Path(name).parts)
        or path.is_symlink()
        or not path.resolve().is_relative_to(directory.resolve())
        or not path.is_file()
    ):
        raise ValueError(f"Missing or unsafe evidence artifact: {name}")
    if path.stat().st_size > limit:
        raise ValueError(f"Evidence artifact exceeds {limit} bytes: {name}")
    return path


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def candidate_count(run):
    """Conservative recorded evaluations, not distinct configurations or model fits."""
    values = [
        run.get("request", {}).get("candidateCount"),
        run.get("metrics", {}).get("n_candidates"),
        run.get("evidenceReview", {}).get("candidateEvaluations"),
    ]
    valid = [int(v) for v in values if _number(v) and v >= 1 and v == int(v)]
    return max(valid, default=1)


def _split_hash(directory, name, folds):
    path = _artifact(directory, name, 4 * 1024 * 1024)
    splits = read_json(path)
    if not isinstance(splits, list) or len(splits) != folds:
        raise ValueError("Split artifact must contain one train/validation entry per fold score.")
    for split in splits:
        if not isinstance(split, dict):
            raise ValueError("Each split must contain train and validation row IDs.")
        sets = []
        for key in ("train", "validation"):
            rows = split.get(key)
            if (
                not isinstance(rows, list)
                or not rows
                or not all(type(row) in (str, int) for row in rows)
            ):
                raise ValueError("Split row IDs must be nonempty lists of strings or integers.")
            if len(set(rows)) != len(rows):
                raise ValueError("Duplicate row IDs within a split partition.")
            sets.append(set(rows))
        if sets[0] & sets[1]:
            raise ValueError("Training and validation row IDs overlap.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_run(root, run):
    directory = Path(root) / ".godel/runs" / identifier(run["id"])
    metric = run["evaluation"]["metric"]
    result = dict(
        runId=run["id"],
        status="incomplete",
        candidateEvaluations=candidate_count(run),
        candidates=[],
        warnings=[],
        errors=[],
        splitHash=None,
        evidenceFile=None,
        selectionConfirmed=False,
    )
    warnings, errors = result["warnings"], result["errors"]
    if run["status"] != "succeeded" or run["measurement"] != "valid":
        errors.append("Run did not finish with a valid numeric measurement.")
    declared = run.get("request", {}).get("candidateCount")
    reported = run.get("metrics", {}).get("n_candidates")
    if reported is not None and (
        not _number(reported) or reported < 1 or reported != int(reported)
    ):
        errors.append("n_candidates must be a positive integer count.")
    elif declared is not None and reported is not None and declared != reported:
        errors.append("Declared candidateCount disagrees with reported n_candidates.")
    manifest = None
    try:
        if (directory / "evaluation.json").exists():
            result["evidenceFile"] = "evaluation.json"
            manifest = read_json(_artifact(directory, "evaluation.json"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("schemaVersion") != 1
                or manifest.get("metric") != metric
            ):
                raise ValueError(
                    "evaluation.json must use schemaVersion 1 and the configured metric."
                )
            candidates = manifest.get("candidates")
            selected = manifest.get("selectedCandidate")
        elif (directory / "candidate_scores.json").exists():
            result["evidenceFile"] = "candidate_scores.json"
            legacy = read_json(_artifact(directory, "candidate_scores.json"))
            candidates = [
                dict(
                    id=name,
                    score=value.get(f"cv_{metric}_mean"),
                    foldScores=value.get(f"fold_{metric}"),
                )
                for name, value in legacy["results"].items()
            ]
            selected = legacy["selected"]
            warnings.append("Legacy candidate evidence lacks an explicit saved split artifact.")
        elif (directory / "fold_scores.json").exists():
            result["evidenceFile"] = "fold_scores.json"
            legacy = read_json(_artifact(directory, "fold_scores.json"))
            candidates = [
                dict(
                    id="single", score=run.get("metrics", {}).get(metric), foldScores=legacy[metric]
                )
            ]
            selected = "single"
        else:
            candidates, selected = [], None
            warnings.append(
                "No candidate/fold evidence. Numeric metrics alone do not validate a model."
            )
        if result["evidenceFile"]:
            if not isinstance(candidates, list) or not 1 <= len(candidates) <= 1000:
                raise ValueError(
                    "Evidence must list 1–1000 candidates, including losing candidates."
                )
            names, fold_count = set(), None
            for candidate in candidates:
                name, score, folds = (
                    candidate.get("id"),
                    candidate.get("score"),
                    candidate.get("foldScores"),
                )
                if not isinstance(name, str) or not 1 <= len(name) <= 120 or name in names:
                    raise ValueError("Candidate IDs must be unique strings of 1–120 characters.")
                names.add(name)
                if (
                    not _number(score)
                    or not isinstance(folds, list)
                    or not 1 <= len(folds) <= 1000
                    or not all(_number(value) for value in folds)
                ):
                    raise ValueError("Each candidate needs a finite score and finite foldScores.")
                if fold_count is not None and len(folds) != fold_count:
                    raise ValueError("Candidates must use the same number of folds.")
                fold_count = len(folds)
                # Schema 1 explicitly defines score as the unweighted fold mean.
                if not math.isclose(statistics.mean(folds), score, rel_tol=1e-7, abs_tol=1e-9):
                    raise ValueError(f"Candidate {name}: score disagrees with its fold mean.")
                result["candidates"].append(
                    dict(
                        id=name,
                        score=score,
                        foldScores=folds,
                        foldStd=statistics.stdev(folds) if len(folds) > 1 else None,
                    )
                )
                if manifest:
                    if (
                        not isinstance(candidate.get("parameters"), dict)
                        or not candidate["parameters"]
                    ):
                        warnings.append(f"{name}: missing resolved model/feature parameters.")
                    prediction = candidate.get("predictionArtifact")
                    if prediction:
                        # Only check existence/identity; evaluators must check OOF coverage/content.
                        prediction_path = _artifact(directory, prediction, 256 * 1024 * 1024)
                        result["candidates"][-1]["predictionArtifact"] = prediction
                        result["candidates"][-1]["predictionBytes"] = prediction_path.stat().st_size
                    else:
                        warnings.append(
                            f"{name}: no held-out prediction artifact for error analysis."
                        )
            if selected not in names:
                raise ValueError("selectedCandidate must name a recorded candidate.")
            chosen = next(c for c in result["candidates"] if c["id"] == selected)
            primary = run.get("metrics", {}).get(metric)
            if not _number(primary) or not math.isclose(
                primary, chosen["score"], rel_tol=1e-7, abs_tol=1e-9
            ):
                raise ValueError("Primary metric disagrees with the selected candidate score.")
            result["selectedCandidate"] = selected
            result["candidateEvaluations"] = max(result["candidateEvaluations"], len(candidates))
            declared = run.get("request", {}).get("candidateCount")
            if declared is not None and declared != len(candidates):
                raise ValueError("Declared candidateCount disagrees with evidence candidate count.")
            if manifest and manifest.get("splitArtifact"):
                result["splitHash"] = _split_hash(directory, manifest["splitArtifact"], fold_count)
            if manifest:
                result["status"] = "documented"
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        RuntimeError,
    ) as error:
        errors.append(str(error))
    if not result["splitHash"]:
        warnings.append(
            "Actual fold membership is not recorded/checked; matching split labels alone are insufficient."
        )
    if result["candidateEvaluations"] > 1:
        warnings.append(
            "Multiple candidates were evaluated. The selected development score is subject to selection bias."
        )
    warnings.append(
        "Fold standard deviation is descriptive, not a confidence interval or proof of improvement."
    )
    warnings.append(
        "Review evaluator code, data provenance, leakage, diagnostics and confirmation design before promotion. Artifact checks do not establish independence."
    )
    if errors:
        result["status"] = "inconsistent"
    return result


def review_experiment(root, run_id, baseline_id=None):
    from .records import get_run

    def load(run_id):
        return get_run(root, run_id)

    run = load(run_id)
    result = review_run(root, run)
    if baseline_id:
        baseline = load(baseline_id)
        previous = review_run(root, baseline)
        result["comparison"] = {"baselineRunId": baseline_id, "paired": False}
        if (
            result["errors"]
            or previous["errors"]
            or run["evaluation"] != baseline["evaluation"]
            or not result["splitHash"]
            or result["splitHash"] != previous["splitHash"]
        ):
            result["comparison"]["reason"] = (
                "Pairing requires valid evidence, matching evaluation and identical saved split artifacts."
            )
        else:
            chosen = next(c for c in result["candidates"] if c["id"] == result["selectedCandidate"])
            reference = next(
                c for c in previous["candidates"] if c["id"] == previous["selectedCandidate"]
            )
            sign = 1 if run["evaluation"]["direction"] == "maximize" else -1
            deltas = [sign * (a - b) for a, b in zip(chosen["foldScores"], reference["foldScores"])]
            result["comparison"].update(
                paired=True,
                improvementByFold=deltas,
                meanImprovement=statistics.mean(deltas),
                wins=sum(d > 0 for d in deltas),
                ties=sum(d == 0 for d in deltas),
                losses=sum(d < 0 for d in deltas),
                caveat="Descriptive comparison only; overlapping CV training sets and adaptive selection preclude naive significance claims.",
            )
    return result
