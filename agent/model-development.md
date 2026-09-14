# ML foundation

Implement solutions independently. Web research may inform ideas; never clone,
copy, translate or adapt others' solution repos, notebooks, pipelines or task
checkpoints, even if public/licensed. Standard libraries and authorized base
models/data are allowed. Cite ideas; write the task code yourself. Disclose
inherited solution reuse and propose replacement while preserving existing work.

Match evaluation to the prediction task and information available at prediction
time. Establish a reference baseline; keep learned transforms within training
partitions and final-test evidence out of tuning. Diagnose held-out errors before
adding complexity. A highest development score is not confirmed generalization;
fold SD is not a confidence interval. Keep the agreed data policy and budget.

Build a credible baseline, then choose the cheapest informative test. Separate the
primary metric from agreed feasibility constraints. Distinguish observed errors,
possible causes, estimated opportunity and measured gains. Do not invent label
corrections or expert baselines; seek evidence or targeted user input when needed.

Use research ideas to shortlist methods. Spend candidate ceilings
in small informative stages; leave room to act on results. Keep stress tests
separate from the primary target metric. Label-free aggregate features still need
matching evaluation/inference semantics. Repeats and new splits do not create
new independent labels. Reject tested configurations, not whole method families.

Maintain a short `protocol.md`: current stage, validation rationale, decisions,
unresolved risks, next diagnostic and confirmation plan. Do not silently replace
a promised validation stage with another search. Use recorded experiments and
review evidence before further tuning or selecting a deliverable. Retain losing
attempts, actual split assignments, held-out predictions and reproducible config.

Load the relevant Godel skill before performing its workflow:

- `ml-validation`: establish/change evaluation or assess confirmation evidence.
- `ml-diagnostics`: explain errors or score gaps and identify the next hypothesis.
- `ml-experiment-design`: plan a controlled comparison or bounded search.
- `ml-reproducibility`: structure experiment code or reproduce a selected result.

Read the matching `SKILL.md` via Pi's catalog or `modelDevelopment.skills`.
Load references as needed. Tools and skills do not prove
model quality or authorize broader actions.
