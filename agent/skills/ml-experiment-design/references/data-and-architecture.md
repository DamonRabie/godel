# Decide whether to change data or architecture

Use this when diagnostics motivate more data, weighting/augmentation, or a
different decomposition. These are experiments under the existing data and
compute policy, not automatic permission to obtain new external data.

Before pooling sources, compare label meaning, units, collection processes and
conditional relationships. More observations from a conflicting task can make a
model worse. A source indicator helps only if it is available at prediction time
and resolves a real distinction; it does not repair arbitrary label conflict.
Use target-representative development evidence to compare source inclusion,
subsampling or weighting against a reference. Record source counts, mixture,
weights and actual compute; a bigger neural network is not a universal remedy.

Synthetic or augmented data must preserve the intended label semantics and
prediction-time constraints. Keep derivatives of an original entity within its
training partition. Record source IDs, transform parameters, seeds and generator
version. Repeated noise tracks, templates or generated objects provide less
diversity than their file count suggests. Judge the intervention on real held-out
target data; visual plausibility or agent approval does not establish realism.
Do not silently treat generated labels as verified observations.

Compare end-to-end and modular designs using available input/output supervision,
intermediate labels, usable pretrained components, compute and diagnostic needs.
Modern pretrained models may reduce fresh-label requirements; the book's
historical domain recommendations are not a current architecture ranking.
Use simpler components when they exploit available supervision or make failures
testable. Keep task-relevant information at interfaces; avoid an elaborate
pipeline that discards information the downstream task needs.

Favor the smallest experiment that can reject an expensive architectural or data
investment. Record expected opportunity, confidence, cost, failure criterion and
observed result. Treat unavailable representative data as an explicit limitation
rather than manufacturing evidence or endlessly tuning the accessible proxy.

Adaptation source: *Machine Learning Yearning*, chapters 4, 23–24, 36–39, 42–43,
47–52. [Original book](https://home-wordpress.deeplearning.ai/wp-content/uploads/2022/03/andrew-ng-machine-learning-yearning.pdf).
