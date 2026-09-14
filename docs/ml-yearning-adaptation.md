# ML Yearning for an autonomous development agent

Godel adapts the decision methods in Andrew Ng's
[Machine Learning Yearning](https://home-wordpress.deeplearning.ai/wp-content/uploads/2022/03/andrew-ng-machine-learning-yearning.pdf).
All 58 chapters were reviewed. The adaptation changes how an agent investigates
and records a problem; it does not prescribe one model family or a universal
sequence of experiments.

## A short, durable decision loop

Establish the prediction task, metric, practical constraints and evaluation
contract. Produce a credible executable baseline. Inspect evidence, name the
leading explanation and a competing explanation, and choose a cheap test whose
possible outcomes change the next decision. Record the result and update the
protocol before adding complexity. A small task may finish at the baseline;
a difficult task may require several cycles.

Human team coordination becomes explicit project state: `protocol.md` stores
decisions and unfinished questions; recorded runs retain evidence; checkpoints
carry the next action across sessions. Questions to the user resolve missing
objectives, domain judgments or scope extensions, rather than routine experiment
choices. Long reports stay in project artifacts. Only the short foundation and
bounded project context are refreshed each turn; detailed skills load on demand.

## Where the methods live

| Book topic | Godel adaptation |
| --- | --- |
| Development/test strategy and iteration (chapters 1–12) | Validation skill: rank feasible candidates by the agreed metric; version changed evaluation contracts and retain exposure history. |
| Error analysis and labeling (13–19) | Diagnostics skill: reproducible error samples, uncertain categories and evidence references; helper counts overlaps without double counting. |
| Fit, generalization and learning curves (20–35) | Diagnostic reference: comparable measurements and budgeted tests; no invented human or attainable-performance reference. |
| Different data distributions (36–41) | Optional source-held-out diagnostics distinguish hypotheses about generalization and population differences while preserving time/group constraints. |
| Search, objectives and data/architecture decisions (42–52) | Compare feasible outputs under the same objective; test source consistency and augmentation lineage; choose architecture using task evidence. |
| Pipeline analysis and synthesis (53–58) | Idealized component substitutions identify conditional opportunities; confirm a realizable intervention before claiming an improvement. |

## Agent-specific limits

An agent's confidence is not label authority or measured expert performance.
Suspected annotation issues need evidence; benchmark labels remain unchanged.
Training/development gaps suggest investigations rather than uniquely identifying
causes. A sampled error category estimates an opportunity under assumptions,
not an expected gain; targeted samples cannot support population extrapolation.
Component interventions can interact and can use information unavailable at
prediction time. Such results remain diagnostics, not deliverable models.

The book's historical architecture examples and numerical heuristics are not
current technology rankings or fixed requirements. Additional partitions,
learning curves, human references and pipeline tests are conditional tools;
the agent should spend its budget on the next unresolved decision.

## Validation boundary

Software tests check skill loading, helper arithmetic and provenance. The
[behavior evaluation protocol](../evals/README.md) adds cross-domain scenarios
for the decisions above. These changes have not yet demonstrated better model
development in controlled agent trials. Measure that separately before promoting
an agent revision on the strength of a single competition result.
