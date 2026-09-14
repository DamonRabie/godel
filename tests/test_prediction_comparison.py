import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "agent/skills/ml-diagnostics/scripts/compare_predictions.py"
)
spec = importlib.util.spec_from_file_location("prediction_comparison", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PredictionComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, rows, fields=None):
        path = self.root / name
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def fixture(self):
        # One row improves then regresses across repeats; another stays correct.
        a = [
            dict(row_id="a", repeat="0", fold="0", target="yes", prediction="no"),
            dict(row_id="b", repeat="0", fold="1", target="no", prediction="no"),
            dict(row_id="a", repeat="1", fold="1", target="yes", prediction="yes"),
            dict(row_id="b", repeat="1", fold="0", target="no", prediction="no"),
        ]
        b = [dict(row) for row in a]
        b[0]["prediction"] = "yes"
        b[2]["prediction"] = "no"
        return a, b

    def test_alignment_repeats_and_opposing_changes(self):
        a, b = self.fixture()
        result = module.compare(self.write("a.csv", a), self.write("b.csv", b[::-1]))
        stats = result["regimes"]["default"]
        self.assertEqual(stats["predictionOccasions"], 4)
        self.assertEqual(stats["uniqueRows"], 2)
        self.assertEqual(stats["changedOccasions"], 2)
        self.assertEqual(stats["changedUniqueRows"], 1)
        self.assertEqual(stats["bothCorrectedAndRegressedUniqueRows"], 1)
        self.assertEqual(stats["accuracyDelta"], 0)
        self.assertEqual(stats["byRepeat"]["0"]["accuracyDelta"], 0.5)
        self.assertEqual(stats["byRepeat"]["1"]["accuracyDelta"], -0.5)

    def test_regimes_stay_separate_and_correctness_recomputed(self):
        a, b = self.fixture()
        for rows in (a, b):
            for i, row in enumerate(rows):
                row.update(regime="ordinary" if i < 2 else "stress", correct="bogus")
        result = module.compare(self.write("a.csv", a), self.write("b.csv", b))
        self.assertEqual(set(result["regimes"]), {"ordinary", "stress"})
        self.assertNotIn("accuracyDelta", result)
        self.assertEqual(result["regimes"]["ordinary"]["accuracyDelta"], 0.5)

    def test_bad_evidence_rejected(self):
        a, b = self.fixture()
        reference = self.write("a.csv", a)
        cases = [
            b[:-1],
            b + [b[0]],
            [dict(row, target="wrong") for row in b],
            [dict(row, fold="changed") for row in b],
            [dict(row, row_id="") for row in b],
        ]
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                module.compare(reference, self.write("b.csv", bad))
        for rows in (a, b):
            rows[2]["target"] = "different"
        with self.assertRaisesRegex(ValueError, "across repeats"):
            module.compare(self.write("a.csv", a), self.write("b.csv", b))

    def test_multiclass_changes_can_leave_both_wrong(self):
        a = [dict(example="opaque-private-id", label="red", output="blue")]
        b = [dict(a[0], output="green")]
        result = module.compare(
            self.write("a.csv", a),
            self.write("b.csv", b),
            id_column="example",
            target_column="label",
            prediction_column="output",
        )
        stats = result["regimes"]["default"]
        self.assertEqual(stats["changedOccasions"], 1)
        self.assertEqual(stats["correctedOccasions"], 0)
        self.assertEqual(stats["regressedOccasions"], 0)
        self.assertNotIn("opaque-private-id", json.dumps(result))

    def test_cli_read_only_and_bounds(self):
        a, b = self.fixture()
        left, right = self.write("a.csv", a), self.write("b.csv", b)
        before = (left.read_bytes(), right.read_bytes())
        process = subprocess.run(
            [sys.executable, str(SCRIPT), str(left), str(right)], text=True, capture_output=True
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["regimes"]["default"]["uniqueRows"], 2)
        self.assertEqual(before, (left.read_bytes(), right.read_bytes()))
        left.write_bytes(b"x" * (module.MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "16 MiB"):
            module.compare(left, right)
        left.write_text("row_id,target,prediction\n")
        with self.assertRaisesRegex(ValueError, "empty"):
            module.compare(left, right)
        left.write_text("row_id,target,prediction,prediction\na,0,0,1\n")
        with self.assertRaisesRegex(ValueError, "Duplicate column"):
            module.compare(left, right)


if __name__ == "__main__":
    unittest.main()
