---
name: ml-diagnostics
description: Analyze baseline or candidate errors before further tuning, investigate unexpected metrics or external-score gaps, and turn held-out evidence into testable modeling hypotheses.
---

# Diagnose before choosing the next model

Review the protocol, candidate records and `godel_review` output, using the CLI
review command in context if the tool is unavailable. Check process outcome,
metric identity and evidence consistency first. Missing evidence is work to
address; it does not establish either model correctness or failure.

For a reproducible error sample, category opportunity estimate or disputed labels,
read [error analysis](references/error-analysis.md); it includes a deterministic
summary helper. For fit/generalization/mismatch, learning curves, objective versus
search failures, or component interventions, read the relevant section of
[diagnostic tests](references/diagnostic-tests.md). Do not load every reference
or run every diagnostic when one test can resolve the next decision.

Use held-out predictions with row/fold IDs. Inspect errors/residuals, confusion,
calibration or ranking failures as appropriate to the task and metric. Compare
baseline and candidate errors on the same observations. Examine a few motivated
slices with sample counts; small or adaptively chosen slices need cautious
interpretation. Keep large predictions in artifacts, not conversation context.
For saved hard-label classification predictions, use
[paired prediction diagnostics](references/paired-predictions.md) to check alignment
and report unique observations separately from repeated prediction occasions.

Separate observations from possible causes. Training/validation gaps and learning
curves can help distinguish capacity, variance, optimization or data limits, but
only when the scores represent comparable data and transformations. For target
encoders with different training/inference transforms, use the
[encoding checks](../ml-validation/references/target-encoding.md).

Investigate plausible data/label quality and prediction-time mismatches before
adding complexity. Use diagnostic tests or small ablations that discriminate
between competing explanations. Do not infer causation from a score difference
or bundle of simultaneous model/feature changes.

Compare development candidates with paired errors or fold differences where
actual split membership matches. Lower fold SD or a small mean increase alone
does not prove a better generalizing model. Inspect losing candidates too;
aggregate rank can hide instability, slice regressions or unacceptable cost.

A local/external score gap may reflect selection, sampling, population changes
or implementation problems; the gap alone does not identify the cause. Public
leaderboard feedback is limited evidence. Do not infer other entrants' methods,
promise perfection or offer hidden-label lookup as a modeling strategy.

Write the observed failure, supporting run/artifact, plausible explanation,
counterevidence and next discriminating experiment in the protocol/report.
Preserve rejected hypotheses so later sessions avoid repeating unsupported work.
Scope rejections to tested implementations and conditions. A losing bundled
representation is not evidence against every feature it contains. A leaderboard
tie or several unsuccessful variants does not establish an accuracy ceiling.
