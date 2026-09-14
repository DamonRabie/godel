import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from godel.cli import api
from godel.context import context
from godel.experiments import comparable, run_experiment
from godel.projects import init_project, read_project
from godel.review import candidate_count, review_experiment, review_run
from godel.storage import atomic_json


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="godel-review-")
        self.home = Path(self.tmp.name)
        shutil.copytree(REPO / "templates", self.home / "templates")
        shutil.copytree(REPO / "agent", self.home / "agent")
        self.root, self.project = init_project(self.home, "example")
        self.project.update(
            evaluation=dict(
                datasetId="fixture-v1", splitId="fixed", metric="mse", direction="minimize"
            )
        )
        atomic_json(self.root / "project.json", self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, scores=(2.0, 4.0), splits=None):
        run_id = str(uuid.uuid4())
        directory = self.root / ".godel/runs" / run_id
        directory.mkdir(parents=True)
        record = dict(
            schemaVersion=1,
            id=run_id,
            projectId=self.project["id"],
            sessionId="test",
            startedAt=run_id,
            status="succeeded",
            measurement="valid",
            evaluation=self.project["evaluation"],
            metrics={"mse": sum(scores) / len(scores)},
            request={"hypothesis": "Controlled change", "candidateCount": 1},
        )
        manifest = dict(
            schemaVersion=1,
            metric="mse",
            selectedCandidate="model",
            splitArtifact="splits.json",
            candidates=[
                dict(
                    id="model",
                    score=record["metrics"]["mse"],
                    foldScores=list(scores),
                    parameters={"depth": 2},
                    predictionArtifact="oof.json",
                )
            ],
        )
        atomic_json(directory / "run.json", record)
        atomic_json(directory / "evaluation.json", manifest)
        atomic_json(
            directory / "splits.json",
            splits
            or [dict(train=[0, 1], validation=[2, 3]), dict(train=[2, 3], validation=[0, 1])],
        )
        atomic_json(
            directory / "oof.json", []
        )  # Existence is not prediction-content certification.
        return record, directory, manifest

    def test_pairing_respects_direction_and_does_not_claim_confirmation(self):
        baseline, _, _ = self.fixture((4, 2))
        candidate, directory, _ = self.fixture((2, 3))
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        result = api(
            self.home,
            self.root,
            "review",
            dict(runId=candidate["id"], baselineRunId=baseline["id"]),
        )
        self.assertEqual(result["comparison"]["improvementByFold"], [2, -1])
        self.assertEqual(result["comparison"]["meanImprovement"], 0.5)
        self.assertEqual((result["comparison"]["wins"], result["comparison"]["losses"]), (1, 1))
        self.assertFalse(result["selectionConfirmed"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_same_split_label_does_not_allow_pairing_different_membership(self):
        baseline, _, _ = self.fixture()
        candidate, _, _ = self.fixture(
            splits=[dict(train=[0, 2], validation=[1, 3]), dict(train=[1, 3], validation=[0, 2])]
        )
        result = review_experiment(self.root, candidate["id"], baseline["id"])
        self.assertFalse(result["comparison"]["paired"])

    def test_bad_evidence_cannot_become_best_even_with_high_numeric_score(self):
        record, directory, manifest = self.fixture()
        manifest["candidates"][0]["foldScores"] = [1, 1]
        atomic_json(directory / "evaluation.json", manifest)
        result = review_run(self.root, record)
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("fold mean", result["errors"][0])
        self.assertIsNone(context(self.home, self.root)["bestMeasuredRun"])

    def test_split_overlap_duplicates_and_evidence_escape_are_rejected(self):
        record, directory, manifest = self.fixture()
        for rows in ([0, 2], [2, 2]):
            atomic_json(
                directory / "splits.json",
                [dict(train=[0, 1], validation=rows), dict(train=[2, 3], validation=[0, 1])],
            )
            self.assertEqual(review_run(self.root, record)["status"], "inconsistent")
        manifest["splitArtifact"] = "../private.json"
        atomic_json(directory / "evaluation.json", manifest)
        self.assertEqual(review_run(self.root, record)["status"], "inconsistent")
        outside = self.home / "private.json"
        outside.write_text('"private-test-secret"')
        (directory / "linked.json").symlink_to(outside)
        manifest["splitArtifact"] = "linked.json"
        atomic_json(directory / "evaluation.json", manifest)
        result = review_run(self.root, record)
        self.assertEqual(result["status"], "inconsistent")
        self.assertNotIn("private-test-secret", json.dumps(result))

    def test_legacy_candidates_remain_reviewable_without_claiming_split_proof(self):
        record, directory, _ = self.fixture()
        (directory / "evaluation.json").unlink()
        record["request"].pop("candidateCount")
        atomic_json(
            directory / "candidate_scores.json",
            dict(
                selected="model",
                results={
                    "model": {"cv_mse_mean": 3, "fold_mse": [2, 4]},
                    "loser": {"cv_mse_mean": 5, "fold_mse": [4, 6]},
                },
            ),
        )
        result = review_run(self.root, record)
        self.assertEqual(result["candidateEvaluations"], 2)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["splitHash"])
        self.assertTrue(any("selection bias" in w for w in result["warnings"]))

    def test_invalid_shapes_and_nonfinite_numbers_are_reported(self):
        record, directory, valid = self.fixture()
        cases = [[], dict(valid, candidates=[]), dict(valid, selectedCandidate="absent")]
        for field, value in (
            ("score", float("nan")),
            ("foldScores", [True, 4]),
            ("foldScores", [2]),
        ):
            case = copy.deepcopy(valid)
            case["candidates"][0][field] = value
            cases.append(case)
        for manifest in cases:
            with self.subTest(manifest=manifest):
                (directory / "evaluation.json").write_text(json.dumps(manifest))
                self.assertEqual(review_run(self.root, record)["status"], "inconsistent")

    def test_live_context_refresh_preserves_protocol_and_losing_experiment(self):
        record, directory, _ = self.fixture()
        record["metrics"].update({f"diagnostic_{i}": i for i in range(100)})
        atomic_json(directory / "run.json", record)
        (self.root / "protocol.md").write_text(
            "Next: diagnose held-out residuals before further tuning."
        )
        value = context(self.home, self.root)
        self.assertIn("residuals", value["modelDevelopment"]["protocol"]["text"])
        self.assertIn("confirmation", value["modelDevelopment"]["guide"]["text"])
        skills = value["modelDevelopment"]["skills"]
        self.assertEqual(len(skills), 4)
        for skill in skills:
            content = Path(skill["path"]).read_text()
            self.assertNotIn(content, json.dumps(value))
            self.assertEqual(Path(skill["path"]).parent.name, skill["name"])
        self.assertFalse(value["modelDevelopment"]["guide"]["truncated"])
        self.assertIn("not a confirmed", value["bestMeasuredRun"]["interpretation"])
        self.assertEqual(value["recentRuns"][0]["hypothesis"], record["request"]["hypothesis"])
        self.assertTrue(value["recentRuns"][0]["metricsTruncated"])
        self.assertEqual(len(value["recentRuns"][0]["metrics"]), 16)
        self.assertIn("mse", value["recentRuns"][0]["metrics"])
        self.assertEqual(len(value["bestMeasuredRun"]["metrics"]), 16)
        (self.root / "protocol.md").write_text("x" * 7000)
        protocol = context(self.home, self.root)["modelDevelopment"]["protocol"]
        self.assertTrue(protocol["truncated"])
        self.assertEqual(len(protocol["text"]), 6000)

    def test_exposure_survives_split_changes_without_ranking_unpaired_scores(self):
        first, _, _ = self.fixture()
        self.project["evaluation"] = dict(self.project["evaluation"], splitId="new-split")
        atomic_json(self.root / "project.json", self.project)
        second, _, _ = self.fixture()
        self.project["evaluation"] = dict(self.project["evaluation"], datasetId="other-data")
        atomic_json(self.root / "project.json", self.project)
        self.fixture()
        self.project["evaluation"] = dict(second["evaluation"])
        atomic_json(self.root / "project.json", self.project)
        value = context(self.home, self.root)
        counts = value["modelDevelopment"]
        self.assertEqual(counts["candidateEvaluationsOnCurrentEvaluation"], 1)
        self.assertEqual(counts["candidateEvaluationsOnCurrentDataset"], 2)
        self.assertEqual(counts["candidateEvaluationsProjectTotal"], 3)
        self.assertEqual(value["bestMeasuredRun"]["id"], second["id"])
        recent = {run["id"]: run for run in value["recentRuns"]}
        self.assertEqual(recent[first["id"]]["evaluation"]["splitId"], "fixed")
        self.assertEqual(recent[second["id"]]["evaluation"]["splitId"], "new-split")

    def test_real_runner_enforces_candidate_budget_and_rejects_underreporting(self):
        self.project["maxCandidatesPerSession"] = 2
        atomic_json(self.root / "project.json", self.project)
        script = self.root / "experiments/fixture.py"
        script.write_text((REPO / "examples/tiny_regression.py").read_text())
        request = dict(
            hypothesis="A line beats a mean baseline",
            command=[sys.executable, str(script)],
            sources=["experiments/fixture.py"],
            timeoutSeconds=5,
        )
        with self.assertRaisesRegex(ValueError, "Declare candidateCount"):
            run_experiment(self.root, request, "test")
        result = run_experiment(self.root, dict(request, candidateCount=1), "test")
        self.assertEqual(result["measurement"], "valid")
        self.assertEqual(result["evidenceReview"]["status"], "inconsistent")
        self.assertEqual(candidate_count(result), 2)
        self.assertFalse(comparable(result, self.project["evaluation"]))
        with self.assertRaisesRegex(ValueError, "candidate budget exhausted"):
            run_experiment(self.root, dict(request, candidateCount=1), "test")

    def test_documented_demo_preserves_predictions_and_records_all_candidates(self):
        script = self.root / "experiments/fixture.py"
        script.write_text((REPO / "examples/tiny_regression.py").read_text())
        result = run_experiment(
            self.root,
            dict(
                hypothesis="Line versus training mean",
                command=[sys.executable, str(script)],
                sources=["experiments/fixture.py"],
                timeoutSeconds=5,
                candidateCount=2,
            ),
            "test",
        )
        self.assertEqual(result["evidenceReview"]["status"], "documented")
        self.assertEqual(len(result["evidenceReview"]["candidates"]), 2)
        directory = self.root / ".godel/runs" / result["id"]
        predictions = json.loads((directory / "linear_predictions.json").read_text())
        recomputed = sum((r["target"] - r["prediction"]) ** 2 for r in predictions) / len(
            predictions
        )
        self.assertAlmostEqual(recomputed, result["metrics"]["mse"])
        self.assertEqual({r["rowId"] for r in predictions}, set(range(80, 100)))

    def test_candidate_cap_validation(self):
        for value in (True, 0, 1.5):
            self.project["maxCandidatesPerSession"] = value
            atomic_json(self.root / "project.json", self.project)
            with self.assertRaises(ValueError):
                read_project(self.root)


if __name__ == "__main__":
    unittest.main()
