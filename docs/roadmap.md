# Iterations

| Iteration | Useful outcome | Evidence and next-step rule |
| --- | --- | --- |
| 1 — implemented foundation | Open an independent Python project in Pi, record a bounded experiment, resume context and reuse reviewed feedback | Offline tests, actual Pi resource loading and synthetic ML smoke. Next: run the first real user project with the chosen provider |
| 2 — first real task | Complete one meaningful ML baseline and an improvement within an agreed scope | Reproducible artifact, valid split, report, actual provider trace, cost and user feedback. Turn concrete failures into regression cases |
| 3 — measured adaptation | Show a candidate prompt/lesson/tool revision improves representative tasks | Compare versioned baseline and candidate on development tasks; check separate holdout tasks and regressions. Repeat or revert when evidence is inconclusive |
| 4 — task-driven capabilities | Add remote compute, tracking, retrieval or UI only where useful | A complete new scenario through execution, failure handling and evidence. Select the capability based on tasks, not a fixed feature checklist |

The first real task should settle data location, target, evaluation design,
deliverable, compute access and budget. The agent asks about consequential gaps
while continuing independent work. The exact first dataset and model provider
remain user choices; no paid inference or remote compute was started during setup.

For harness improvement, retain the Git revision, prompt/template hashes, model
ID, lesson snapshot, task versions and evaluation results. Begin with human
curation; consider GEPA-style prompt optimization only after a useful task suite
exists. Consider automatic code evolution only after reliable candidate isolation,
independent scoring and rollback exist.
