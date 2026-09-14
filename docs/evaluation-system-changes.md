# Evaluation system: latest changes

Updated 2026-09-14. This report covers the implementation-plan review and the subsequent clarification about individual assessment, batch learning and the capability radar. The evaluator remains a proposed external system; the HTML viewer is implemented. No agent capability scores or improvement claims were produced.

## Artifacts

- The detailed implementation plan is a local design artifact, excluded from this
  repository. The public design summary and viewer contract are documented below;
  they do not require access to that private artifact.
- [Agent capability radar](agent-capability-radar.html): one standalone HTML file with an embedded SVG radar, the nine pillars, an accessible score table, profile import and SVG export. Open it directly in a browser; no server, dependency installation, network access or model credential is needed.

## What changed in the plan

| Area | Previous gap | Completed design |
| --- | --- | --- |
| System boundary | Generic feedback loop around Pi | Separate proposed `godel-evaluator` sibling repository; Godel retains runtime, project and execution ownership |
| Paths and systems | Abstract memory/procedure targets | Exact `src/godel/`, `pi/`, `agent/`, `templates/project/`, `evals/`, SQLite and MLflow owners |
| Evidence | A generic “run” and episodic log store | Explicit task/session/experiment/trial identities; read-only schema-3 connector; pending versus acknowledged history; integrity and missing-evidence handling |
| Capability assessment | Every dimension expected a score | Nine anchored dimensions, null/not-applicable results, observation coverage, citations and judge calibration |
| Individual versus batch | Per-attempt scope existed; cross-attempt learning was implicit | Explicit per-attempt assessment followed by immutable assessment batches, pattern synthesis and evidence-backed proposals |
| Validation | Historical logs treated as potential behavioral replay | Separate retrospective diagnosis, deterministic checks and fresh controlled agent trials |
| Trial execution | An unspecified isolated Pi harness | Fresh Godel copies, pinned Pi RPC, independent state/ports/lessons, actual model identity, budgets and crash reconciliation |
| Versioning | Assumed source revisions | Git revisions for committed source, with hashed source snapshots for uncommitted changes |
| Adaptation | Promotion conflated eligibility and mutation | Deterministic eligibility, reviewable package, operator adoption, parent checks, idempotent receipts and scoped rollback |
| Delivery | Broad phases without complete handoff | Five vertical iterations, concrete work packages, verification and requirement coverage |
| Reporting | Radar described but not supplied | Offline HTML viewer and a documented profile format; no fabricated measured profile |

## Individual assessment and batch learning

The proposed assessment workflow is:

1. Assess one complete task attempt with its relevant instructions, events, experiments and artifacts. Individual log lines are not assessment units.
2. Run independent assessment jobs concurrently when resources allow. This does not merge their contexts or scores.
3. Freeze a batch of completed assessments, with identities, versions, inclusion/exclusion reasons and coverage counts.
4. Find recurring patterns and contradictions using the assessments, retrieving original evidence when necessary. Provisional per-attempt lessons become inputs to batch synthesis.
5. Propose a small intervention and validate it on fresh baseline/candidate tasks. A single serious failure can motivate a targeted proposal, but retains its single-episode label and still needs validation.

Batch profiles group compatible runtime/model/lesson/rubric versions and task families. Each radar value is the median of assessable attempts for that pillar, with the assessed/eligible count displayed. Missing scores stay missing. A batch median describes that cohort, not universal agent power, and does not determine promotion by itself.

## Using the radar

Open [agent-capability-radar.html](agent-capability-radar.html). It initially displays all nine axes with **Awaiting assessment** and no capability polygon. Software-test results are not converted into capability scores.

- **Get JSON template** downloads a complete unassessed profile with all nine IDs.
- **Import profile** loads a local JSON file, validates it, and redraws the one radar. It does not fetch or verify evidence behind the supplied references. Invalid imports preserve the prior profile.
- **Export SVG** downloads the chart with a scope/version caption and embedded profile metadata.
- **Clear** removes the imported profile from the page. Refresh also resets it; no browser storage is used.

The radar and table use the plan's exact pillars:

| ID | Pillar |
| --- | --- |
| `problem_understanding` | Problem Understanding |
| `data_reasoning` | Data Reasoning |
| `modeling` | Modeling & ML Knowledge |
| `experimental_reasoning` | Experimental Reasoning |
| `evaluation_diagnosis` | Evaluation & Diagnosis |
| `engineering` | Engineering & Implementation |
| `debugging` | Debugging & Recovery |
| `planning_resources` | Planning & Resource Management |
| `learning_adaptation` | Learning & Adaptation |

### Radar profile format, version 1

This is a **display contract**, not a claim that the evaluator's future canonical `Assessment` schema is implemented. Its report exporter will map one assessment or one compatible batch into this format. The downloadable template includes all fields and dimensions.

| Field | Contract |
| --- | --- |
| `schema_version` | `1` |
| `profile_id`, `title` | Nonempty identifiers/display text, maximum 500 characters each |
| `scope` | `unassessed`, `attempt`, or `batch` |
| `attempt_count` | Zero for unassessed; exactly one for attempt; positive integer for batch |
| `assessed_at` | ISO timestamp with timezone; required for attempt/batch |
| `runtime_version`, `model`, `rubric_version`, `lesson_snapshot` | Nonempty provenance strings for attempt/batch; use the actual source versions |
| `task_families` | Unique nonempty family names; required for attempt/batch |
| `source_assessment_ids` | One distinct source assessment ID per attempt; do not count revised assessments twice |
| `dimensions` | Exactly one object for each of the nine IDs; input order does not matter |
| `dimensions[].score` | Integer 1–5 for an attempt; median in [1,5] for a batch; `null` when unassessed |
| `dimensions[].confidence` | `null` or evidence-support value in [0,1]; unscored dimensions require `null`. Do not manufacture an aggregate probability for a batch. |
| `dimensions[].assessed_attempts` | Nonnegative integer; zero if score is null; positive if scored |
| `dimensions[].eligible_attempts` | Nonnegative integer, at least assessed count and no larger than total attempt count; excludes no-opportunity attempts |
| `dimensions[].evidence_refs` | Evidence identifier strings; at least one required for a scored pillar |

Files are limited to 1 MiB. Unknown/duplicate dimension IDs, out-of-range scores, impossible counts and missing required provenance are rejected. A partial profile draws observed points and only adjacent observed segments; it never connects across a missing pillar or plots missing values at zero. A complete profile draws a filled nine-sided shape. The table remains the authoritative readable score display.

The viewer does not calculate batch medians from raw attempts, calibrate confidence, assess logs, query MLflow, run trials, certify imported evidence or adopt changes. Those remain external-evaluator responsibilities in the plan. No fake/demo profile is presented as measured Godel capability.

## Verification

Verified on 2026-09-14:

- Plan/report links resolve, the graph explicitly includes batch synthesis, and all nine chart IDs match the capability rubric.
- Browser checks passed for the empty state, JSON template download, full profile import, SVG export with provenance metadata, partial profiles with gaps, invalid-score rejection without losing the prior profile, duplicate-ID rejection, fractional batch medians and clearing.
- Desktop labels fit inside the radar; the 390-pixel mobile layout has no horizontal page overflow. No JavaScript errors occurred during the browser checks. Synthetic test profiles were used only for verification and are not embedded as live capability results.
- `make verify` passed: 3 Pi tests passed; 59 Python tests ran, with 49 passed and 10 optional real-tracking tests skipped.

Browser verification used a temporary localhost server because the browser tool blocks direct `file:` navigation. The delivered file has inline CSS/JavaScript and requires no server for normal use. No live provider evaluation, real capability scoring, evaluator implementation, harness runtime change or adoption was performed.
