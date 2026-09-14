#!/usr/bin/env python3
"""Read-only paired hard-label classification diagnostics; Python stdlib only."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 100_000


def read_predictions(path, *, id_column, target_column, prediction_column):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Prediction file exceeds 16 MiB")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    columns = reader.fieldnames or []
    required = {id_column, target_column, prediction_column}
    if len(required) != 3 or not required.issubset(columns):
        raise ValueError("Distinct ID, target and prediction columns are required")
    if len(columns) != len(set(columns)):
        raise ValueError("Duplicate column names")
    # Never silently collapse multiple repeats, folds or evaluation regimes.
    dimensions = [name for name in ("regime", "repeat", "fold") if name in columns]
    if required.intersection(dimensions):
        raise ValueError("Identity/label columns must differ from regime/repeat/fold")
    result = {}
    for row in reader:
        if len(result) >= MAX_ROWS:
            raise ValueError("Prediction file exceeds 100000 rows")
        if None in row or any(
            row.get(name) is None or not row[name].strip() for name in [*required, *dimensions]
        ):
            raise ValueError("Malformed row or empty required value")
        if any(len(row[name]) > 256 for name in [*required, *dimensions]):
            raise ValueError("Identity/label value exceeds 256 characters")
        key = tuple(row[name] for name in [id_column, *dimensions])
        if key in result:
            raise ValueError("Duplicate observation key; preserve repeat/fold/regime")
        result[key] = (
            row[id_column],
            row.get("regime", "default"),
            row.get("repeat", "0"),
            row[target_column],
            row[prediction_column],
        )
    if not result:
        raise ValueError("Prediction file is empty")
    return result, dimensions, hashlib.sha256(raw).hexdigest()


def _summary(pairs):
    corrected, regressed, changed = set(), set(), set()
    reference_correct = candidate_correct = changes = fixes = harms = 0
    for ref, new in pairs:
        row_id, _, _, target, old_prediction = ref
        prediction = new[4]
        old_ok, new_ok = old_prediction == target, prediction == target
        reference_correct += old_ok
        candidate_correct += new_ok
        if old_prediction != prediction:
            changes += 1
            changed.add(row_id)
        if new_ok and not old_ok:
            fixes += 1
            corrected.add(row_id)
        if old_ok and not new_ok:
            harms += 1
            regressed.add(row_id)
    n = len(pairs)
    return dict(
        predictionOccasions=n,
        uniqueRows=len({r[0] for r, _ in pairs}),
        changedOccasions=changes,
        changedUniqueRows=len(changed),
        correctedOccasions=fixes,
        regressedOccasions=harms,
        correctedUniqueRows=len(corrected),
        regressedUniqueRows=len(regressed),
        bothCorrectedAndRegressedUniqueRows=len(corrected & regressed),
        referenceAccuracy=reference_correct / n,
        candidateAccuracy=candidate_correct / n,
        accuracyDelta=(fixes - harms) / n,
    )


def compare(
    reference,
    candidate,
    *,
    id_column="row_id",
    target_column="target",
    prediction_column="prediction",
):
    options = dict(
        id_column=id_column, target_column=target_column, prediction_column=prediction_column
    )
    left, left_dims, left_hash = read_predictions(reference, **options)
    right, right_dims, right_hash = read_predictions(candidate, **options)
    if left_dims != right_dims or left.keys() != right.keys():
        raise ValueError("Prediction keys or regime/repeat/fold dimensions differ")
    targets = {}
    buckets = {}
    for key, ref in left.items():
        new = right[key]
        if ref[3] != new[3]:
            raise ValueError("Paired targets differ")
        if ref[0] in targets and targets[ref[0]] != ref[3]:
            raise ValueError("Target changed for an observation across repeats/regimes")
        targets[ref[0]] = ref[3]
        buckets.setdefault(ref[1], []).append((ref, new))
    if len(buckets) > 32:
        raise ValueError("Too many regimes for a bounded summary")
    regimes = {}
    for name, pairs in sorted(buckets.items()):
        repeats = sorted({ref[2] for ref, _ in pairs})
        if len(repeats) > 100:
            raise ValueError("Too many repeats for a bounded summary")
        regimes[name] = dict(
            _summary(pairs),
            byRepeat={
                repeat: _summary([(r, n) for r, n in pairs if r[2] == repeat]) for repeat in repeats
            },
        )
    return dict(
        schemaVersion=1,
        referenceSha256=left_hash,
        candidateSha256=right_hash,
        regimes=regimes,
        interpretation=(
            "Descriptive unweighted hard-label accuracy, pooled by prediction occasion "
            "within each regime. Repeated rows are dependent; no combined-regime score, "
            "confidence interval, significance test or promotion decision. String labels "
            "must use identical encoding. Matching keys/targets do not verify training "
            "membership, out-of-fold provenance, leakage or an independent test. "
            "Corrected/regressed unique-row sets can overlap across repeats."
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--id-column", default="row_id")
    parser.add_argument("--target-column", default="target")
    parser.add_argument("--prediction-column", default="prediction")
    args = parser.parse_args()
    try:
        result = compare(**vars(args))
    except (OSError, ValueError, csv.Error) as error:
        # Avoid echoing a malformed CSV's raw contents into the session.
        print(
            f"Cannot compare predictions ({type(error).__name__}): "
            + (str(error) if type(error) is ValueError else "check files and CSV encoding"),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
