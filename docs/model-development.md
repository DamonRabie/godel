# Developing models with Godel

The staged-search workflow uses relevant original methods to shortlist tests,
then adapts after small batches. Read
[research and screening](../agent/skills/ml-experiment-design/references/research-and-screening.md)
when starting a familiar task or plateauing. Detailed sources and a hypothesis
frontier stay in the project's reports; only the current decision belongs in
the bounded protocol. Prior work suggests tests, not guaranteed scores.

Context includes recorded exposure on the current evaluation, across all splits
of the declared dataset, and across the project. Recent runs carry evaluation
definitions so unpaired scores stay distinguishable. These are not remaining
budget counts and cannot detect renamed or overlapping datasets automatically.

For saved hard-label classification evidence,
[paired prediction diagnostics](../agent/skills/ml-diagnostics/references/paired-predictions.md)
provides a read-only Python helper. It aligns IDs/repeats/folds/regimes, recomputes
accuracy, and distinguishes changed prediction occasions from unique observations.
It does not combine stress and primary regimes or certify out-of-fold provenance.
See [batch and regime validation](../agent/skills/ml-validation/references/batch-and-regime-validation.md)
for aggregate-feature reference populations and justified evaluation mixtures.

The short [ML foundation](../agent/model-development.md) is refreshed each turn,
together with the project's `protocol.md`, recent hypotheses/results and cumulative
candidate exposure on the current evaluation. Detailed workflows are Pi skills
loaded on demand. They apply across model families and tasks; old conversations
and the full skill library are not bulk-loaded.
Missing protocols are surfaced for existing projects; the harness never rewrites
their working files or past checkpoints automatically.

Use the protocol to keep the prediction-time assumptions, validation rationale,
current stage, rejected hypotheses, next diagnostic and confirmation plan durable.
Keep long results in reports. A plan to investigate validation must not disappear
when a new search becomes attractive.

## Skills

| Skill | Load when |
| --- | --- |
| [ml-validation](../agent/skills/ml-validation/SKILL.md) | Establishing/changing evaluation, auditing leakage or assessing confirmation |
| [ml-diagnostics](../agent/skills/ml-diagnostics/SKILL.md) | Inspecting held-out errors, score gaps and competing explanations |
| [ml-experiment-design](../agent/skills/ml-experiment-design/SKILL.md) | Planning the next controlled experiment or bounded search |
| [ml-reproducibility](../agent/skills/ml-reproducibility/SKILL.md) | Structuring experiment code or reproducing a selected deliverable |

Each directory has standard `SKILL.md` frontmatter with a name and description.
Pi puts those descriptions in its skill catalog; the agent reads the relevant
body when needed. Linked references cover evaluation contracts, error analysis,
diagnostic tests, data/architecture choices and target encoding. Load only the
reference relevant to the current decision. See the
[ML Yearning adaptation](ml-yearning-adaptation.md) for the rationale.
The foundation instructs the agent to load the appropriate skill before doing
its workflow; this is model guidance, not deterministic dispatch or certification.
Python tools perform executable checks; skills do not grant additional authority.
The diagnostics skill includes a read-only Python helper for error-category
counts and conditional improvement ceilings. Its
[input contract and usage](../agent/skills/ml-diagnostics/references/error-analysis.md)
explain sampling limits and overlapping categories. It checks arithmetic and
structure, not the truth of annotations or the representativeness of a sample.

Use `/skill:ml-validation` (or another skill name) to invoke one explicitly.
Normal implicit selection remains enabled. The launcher keeps `--no-skills`
to disable ambient discovery and adds explicit `--skill` paths under this
repository's `agent/skills/`. Global, ancestor, package and project-local skills
are not automatically imported. This preserves configuration isolation, not an
OS sandbox. Godel's skills rely on the tools and conventions of this workspace;
their standard format does not imply they work unchanged in every other harness.

Restart/resume Godel to register the new catalog and slash commands:
`python3 bin/godel.py chat <project> --continue` from the harness root. An
already-open session receives the short foundation and skill file paths on its
next turn, so it can read the skills directly without stopping current work.

To extend the library, add `agent/skills/<name>/SKILL.md` with a matching name and
a precise description, plus only references/scripts that the workflow needs.
Keep essential invariants in the foundation and executable logic in Python.
Add the skill to the explicit expected catalog in the Pi integration test, run
`make verify`, then evaluate model behavior on representative tasks. Startup
history hashes include skill entrypoints, Markdown references and Python helpers
for provenance.

## Evidence review

Inside Pi, call `godel_review` with `runId` and optional `baselineRunId`.
From another terminal, or a session opened before that tool was installed:

```bash
python3 bin/godel.py review <project> <run-id>
python3 bin/godel.py review <project> <run-id> --baseline <baseline-run-id>
```

This is read-only: no training, network calls, history changes or promotion.
Reviews distinguish missing evidence from inconsistent evidence. Inconsistent
new evidence is retained with the run but excluded from best-score eligibility;
context also checks older artifacts before selecting its highest recorded score.
`measurement: valid` still means finite numeric metrics with the primary key.
`evidenceReview.status: documented` means the supplied format passed these checks,
not that the experiment is independent, leakage-free or statistically convincing.
`selectionConfirmed` stays false: this tool cannot certify a scientific conclusion.

Checks cover candidate IDs/counts, finite scores, fold means, the selected primary
metric, artifact paths, and duplicate/overlapping IDs within each saved split.
Paired comparisons require matching evaluation metadata and byte-identical split
artifacts; positive deltas always mean improvement, for either metric direction.
They report descriptive wins/ties/losses, not p-values or confidence intervals.
Identical split files do not prove the training program actually used them.

The reviewer does **not** verify actual dataset hashes, group/time separation,
the content/coverage of prediction files, whether every searched candidate was
reported, or whether holdout evidence was previously consulted. Project evaluator
tests and code review must establish those properties. Files are locally mutable;
source snapshots and records are provenance aids, not tamper-proof attestations.

## Run artifact contract

Write normal finite metrics to `$GODEL_RUN_DIR/metrics.json`. Also write an
`evaluation.json` (maximum 256 KiB) in that run directory. Schema 1 represents
scores as **unweighted means across the listed folds**, for any numeric metric.
A single holdout is one fold. Do not misrepresent a pooled or weighted metric as
an unweighted mean: document it separately or extend the contract with tests.

```json
{
  "schemaVersion": 1,
  "metric": "accuracy",
  "selectedCandidate": "tree_depth4",
  "splitArtifact": "splits.json",
  "candidates": [
    {
      "id": "dummy",
      "score": 0.6,
      "foldScores": [0.5, 0.7],
      "parameters": {"strategy": "most_frequent"},
      "predictionArtifact": "dummy_oof.csv"
    },
    {
      "id": "tree_depth4",
      "score": 0.75,
      "foldScores": [0.7, 0.8],
      "parameters": {"max_depth": 4, "seed": 42, "features": "v1"},
      "predictionArtifact": "tree_oof.csv"
    }
  ]
}
```

Corresponding `metrics.json`: `{"accuracy": 0.75, "n_candidates": 2}`.
`splits.json` contains the actual stable row IDs used by the evaluator, in fold
score order. Record repeat/fold naming conventions in the protocol. For example:

```json
[
  {"train": [0, 1], "validation": [2, 3]},
  {"train": [2, 3], "validation": [0, 1]}
]
```

Splits are bounded at 4 MiB. At larger scale retain a compact split manifest in
project artifacts and extend the reviewer deliberately; don't invent a small
split file that differs from the evaluator. Prediction references are checked
as regular files up to 256 MiB; they are not read into model context. Include
row ID, repeat/fold ID, target and prediction/probability as appropriate; never
include private data unnecessarily. Also retain data fingerprints and resolved
config/dependency files with each experiment.

Older `fold_scores.json` (`{metric: [scores]}`) and `candidate_scores.json`
(`selected`, `results`, `cv_<metric>_mean`, `fold_<metric>`) can be reviewed.
Their split membership remains unverified; they are not silently upgraded into
confirmed evidence. Unknown formats produce missing-evidence guidance.

An executable dependency-free example is
[tiny_regression.py](../examples/tiny_regression.py): it records a mean baseline,
a fitted line, split membership and validation predictions. It demonstrates
artifact plumbing, not agent competence or a universal modeling recipe.

## Candidate budgets

`candidateCount` declares the number of configurations evaluated in a recorded
process, including re-evaluated baselines. The runner passes this value through
`GODEL_CANDIDATE_COUNT` so a batch can assert its planned candidate count.
Folds, seeds and estimator fits have different costs; record those separately.

An optional `maxCandidatesPerSession` in `project.json` adds a ceiling distinct
from `maxRunsPerSession`. Configure or change ceilings only within the user's
authorization. For an extension, account for prior evaluations; adding ten
candidates does not mean setting a total cap of ten or adding ten run slots.
With a candidate ceiling, requests must declare candidateCount. Failed attempts
consume their declared allocations; reported larger counts are retained and
counted conservatively. Legacy counts use `n_candidates` when available and
otherwise one; this may undercount unreported searches. Shell execution and
false declarations cannot be prevented by this non-sandboxed harness.

## Why these practices

Selecting and evaluating hyperparameters on the same data can yield an
optimistic estimate; nested CV evaluates the selection procedure. Repeated
development CV alone does not remove adaptive selection bias.
[scikit-learn: nested versus non-nested CV](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html).

The split should reflect dependence and the prediction population. Group splits
test new-group generalization; they are not automatically the right replacement
for every random split. Stratification can also conceal some inter-fold
variability. [scikit-learn: cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html).

Target encoding needs special care about the training representation, not just
outer validation isolation. Internal cross-fitting helps control overfitting of
downstream predictors. [scikit-learn: target-encoder cross-fitting](https://scikit-learn.org/stable/auto_examples/preprocessing/plot_target_encoder_cross_val.html).

These are design foundations, not a claim that the updated agent performs better.
Use the [behavior evaluation protocol](../evals/README.md) on separate tasks to
measure that, including regressions and cost.
