"""Summarize an explicit unweighted error audit; no raw data or model access."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

INPUT_LIMIT = 2 * 1024 * 1024


def summarize(audit):
    if (
        not isinstance(audit, dict)
        or type(audit.get("schemaVersion")) is not int
        or audit["schemaVersion"] != 1
    ):
        raise ValueError("Expected error audit schemaVersion 1.")
    run_id = audit.get("runId")
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 120:
        raise ValueError("runId must identify the reviewed run.")
    population = audit.get("population")
    if not isinstance(population, dict):
        raise ValueError("population must specify examples and errors.")
    examples, errors = population.get("examples"), population.get("errors")
    if (
        type(examples) is not int
        or type(errors) is not int
        or not 1 <= examples <= 10**12
        or not 0 <= errors <= examples
    ):
        raise ValueError(
            "Population counts must be integers with 0 <= errors <= examples <= 10^12."
        )
    sampling = audit.get("sampling")
    if sampling not in ("all_errors", "uniform_errors", "purposive_errors"):
        raise ValueError("Specify all_errors, uniform_errors or purposive_errors sampling.")
    records = audit.get("records")
    if not isinstance(records, list) or not 0 <= len(records) <= min(errors, 5000):
        raise ValueError(
            "records must list at most 5000 reviewed errors and cannot exceed population errors."
        )
    if sampling == "all_errors" and len(records) != errors:
        raise ValueError("all_errors requires every population error to be reviewed.")
    ids, counts, covered = set(), Counter(), 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each record must be an object.")
        row_id = record.get("id")
        if not isinstance(row_id, str) or not 1 <= len(row_id) <= 200 or row_id in ids:
            raise ValueError(
                "Reviewed IDs must be unique nonempty strings of at most 200 characters."
            )
        ids.add(row_id)
        evidence = record.get("evidence")
        if not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 2000:
            raise ValueError("Each reviewed error needs a bounded evidence reference.")
        categories = record.get("categories")
        if (
            not isinstance(categories, list)
            or len(categories) > 30
            or not all(isinstance(c, str) and 1 <= len(c.strip()) <= 100 for c in categories)
            or len(set(categories)) != len(categories)
        ):
            raise ValueError(
                "categories must be unique nonempty strings; use [] for unclassified errors."
            )
        counts.update(categories)
        covered += bool(categories)
    reviewed = len(records)

    def opportunity(count):
        if sampling == "purposive_errors" or not reviewed:
            return None
        return 100 * (errors / examples) * (count / reviewed)

    categories = [
        dict(
            category=name,
            reviewedErrors=count,
            shareOfReviewedErrors=count / reviewed,
            conditionalHeadroomPp=opportunity(count),
        )
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return dict(
        runId=run_id,
        sampling=sampling,
        populationErrorRate=errors / examples,
        reviewedErrors=reviewed,
        unclassifiedErrors=reviewed - covered,
        coveredErrors=covered,
        categories=categories,
        coveredConditionalHeadroomPp=opportunity(covered),
        headroomMeaning=(
            "not estimated from targeted or empty samples"
            if sampling == "purposive_errors" or not reviewed
            else "conditional ceiling on this population"
            if sampling == "all_errors"
            else "sample estimate with unquantified sampling and annotation uncertainty"
        ),
        assumptions=[
            "Only unweighted binary error rates; all listed rows must be genuine errors.",
            "Headroom assumes fixing every categorized error without introducing other errors; it is not an expected gain.",
            "Categories overlap. Do not sum their headroom; coveredErrors counts the union.",
            "Sampling claims, population counts and annotations are supplied, not verified by this helper.",
        ],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "audit", type=Path, help="Project error-audit JSON; the input is never modified"
    )
    args = parser.parse_args(argv)
    try:
        with args.audit.open("rb") as stream:
            raw = stream.read(INPUT_LIMIT + 1)
        if len(raw) > INPUT_LIMIT:
            raise ValueError("Audit exceeds 2 MiB; use a bounded inspection sample.")
        result = summarize(json.loads(raw))
    except (OSError, ValueError, TypeError) as error:
        print(f"error-audit: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
