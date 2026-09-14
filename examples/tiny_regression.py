"""A deterministic, dependency-free experiment for testing the harness."""

import json
import os
from pathlib import Path
import random

rng = random.Random(17)
rows = [(x := rng.uniform(-5, 5), 3 * x + 2 + rng.gauss(0, 0.2)) for _ in range(100)]
train, validation = rows[:80], rows[80:]
mean_x = sum(x for x, _ in train) / len(train)
mean_y = sum(y for _, y in train) / len(train)
slope = sum((x - mean_x) * (y - mean_y) for x, y in train) / sum(
    (x - mean_x) ** 2 for x, _ in train
)
intercept = mean_y - slope * mean_x
mse = sum((slope * x + intercept - y) ** 2 for x, y in validation) / len(validation)
baseline = sum((mean_y - y) ** 2 for _, y in validation) / len(validation)
metrics = {"mse": mse, "baseline_mse": baseline, "n_candidates": 2}
run_dir = Path(os.environ["GODEL_RUN_DIR"])
(run_dir / "metrics.json").write_text(json.dumps(metrics))
(run_dir / "model.json").write_text(json.dumps({"slope": slope, "intercept": intercept}))
(run_dir / "splits.json").write_text(
    json.dumps([{"train": list(range(80)), "validation": list(range(80, 100))}])
)
for name, predictions in (
    ("mean", [mean_y for _ in validation]),
    ("linear", [slope * x + intercept for x, _ in validation]),
):
    (run_dir / f"{name}_predictions.json").write_text(
        json.dumps(
            [
                {"rowId": 80 + i, "fold": 0, "target": y, "prediction": prediction}
                for i, ((_, y), prediction) in enumerate(zip(validation, predictions))
            ]
        )
    )
(run_dir / "evaluation.json").write_text(
    json.dumps(
        {
            "schemaVersion": 1,
            "metric": "mse",
            "selectedCandidate": "linear",
            "splitArtifact": "splits.json",
            "candidates": [
                {
                    "id": "mean",
                    "score": baseline,
                    "foldScores": [baseline],
                    "parameters": {"strategy": "training_mean"},
                    "predictionArtifact": "mean_predictions.json",
                },
                {
                    "id": "linear",
                    "score": mse,
                    "foldScores": [mse],
                    "parameters": {"slope": slope, "intercept": intercept},
                    "predictionArtifact": "linear_predictions.json",
                },
            ],
        }
    )
)
print(json.dumps(metrics))
