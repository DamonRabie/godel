import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "agent/skills/ml-diagnostics/scripts/summarize_errors.py"
spec = importlib.util.spec_from_file_location("godel_error_audit", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ErrorAuditTests(unittest.TestCase):
    def audit(self, sampling="all_errors"):
        return dict(
            schemaVersion=1,
            runId="fixture-run",
            population=dict(examples=40, errors=4),
            sampling=sampling,
            records=[
                dict(id="a", categories=["missing", "noise"], evidence="prediction a"),
                dict(id="b", categories=["missing"], evidence="prediction b"),
                dict(id="c", categories=["noise"], evidence="prediction c"),
                dict(id="d", categories=[], evidence="cause unknown"),
            ],
        )

    def test_overlap_is_not_double_counted_and_unknowns_stay_in_denominator(self):
        result = module.summarize(self.audit())
        self.assertEqual(result["populationErrorRate"], 0.1)
        self.assertEqual(result["coveredErrors"], 3)
        self.assertEqual(result["unclassifiedErrors"], 1)
        self.assertAlmostEqual(result["coveredConditionalHeadroomPp"], 7.5)
        for category in result["categories"]:
            self.assertEqual(category["shareOfReviewedErrors"], 0.5)
            self.assertAlmostEqual(category["conditionalHeadroomPp"], 5.0)

    def test_uniform_error_sample_is_an_estimate_not_guaranteed_gain(self):
        audit = self.audit("uniform_errors")
        audit["population"] = dict(examples=2000, errors=100)
        result = module.summarize(audit)
        self.assertAlmostEqual(result["categories"][0]["conditionalHeadroomPp"], 2.5)
        self.assertIn("sample estimate", result["headroomMeaning"])

    def test_targeted_sample_does_not_extrapolate_to_population(self):
        result = module.summarize(self.audit("purposive_errors"))
        self.assertIsNone(result["coveredConditionalHeadroomPp"])
        self.assertTrue(all(c["conditionalHeadroomPp"] is None for c in result["categories"]))
        self.assertEqual(result["categories"][0]["reviewedErrors"], 2)

    def test_empty_audit_does_not_invent_evidence(self):
        audit = self.audit()
        audit["population"]["errors"] = 0
        audit["records"] = []
        result = module.summarize(audit)
        self.assertEqual(result["categories"], [])
        self.assertEqual(result["reviewedErrors"], 0)
        self.assertIsNone(result["coveredConditionalHeadroomPp"])

    def test_invalid_counts_duplicate_ids_and_missing_evidence_fail(self):
        cases = [[], dict(self.audit(), schemaVersion=True)]
        for examples, errors in ((True, 1), (10, 11), (10, -1), (10, 1.2)):
            cases.append(dict(self.audit(), population=dict(examples=examples, errors=errors)))
        bad = self.audit()
        bad["records"][1]["id"] = "a"
        cases.append(bad)
        bad = self.audit()
        bad["records"][0]["categories"] = ["missing", "missing"]
        cases.append(bad)
        bad = self.audit()
        bad["records"][0].pop("evidence")
        cases.append(bad)
        bad = self.audit()
        bad["records"].pop()
        cases.append(bad)
        for audit in cases:
            with self.subTest(audit=audit), self.assertRaises(ValueError):
                module.summarize(audit)

    def test_cli_is_read_only_and_omits_raw_row_evidence(self):
        with tempfile.TemporaryDirectory(prefix="godel-error-audit-") as temporary:
            path = Path(temporary) / "audit.json"
            audit = self.audit()
            audit["records"][0]["evidence"] = "private-row-details"
            path.write_text(json.dumps(audit))
            before = path.read_bytes()
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, timeout=5
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("private-row-details", result.stdout)
            self.assertEqual(json.loads(result.stdout)["coveredErrors"], 3)
            path.write_bytes(b"x" * (module.INPUT_LIMIT + 1))
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, timeout=5
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("2 MiB", result.stderr)


if __name__ == "__main__":
    unittest.main()
