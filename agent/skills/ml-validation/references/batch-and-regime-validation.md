# Validate the information available at use

Read when testing aggregate/group features, batch prediction, or multiple split
regimes. Label-free does not automatically mean evaluation matches deployment.

## Give each regime a purpose

Distinguish the primary estimate for the prediction population from stress tests
for changed conditions. Known-entity and unseen-entity prediction are different
questions. A group-disjoint split can be essential for new entities and only a
stress test when future observations legitimately have labeled training peers.
For overlapping relationship keys, connected components may be needed to make
an unseen-group test disjoint. Missing/shared placeholder keys are not relations.

Report each regime separately with row counts, repeat counts, metric aggregation
and reference deltas. Do not average fifteen random folds with five group folds
and silently make a 75/25 population assumption. Repetition count is a precision
choice, not a population weight. Only define a combined selection metric when
its weights correspond to a justified target mixture or an agreed utility.
An unsupported stress-test tolerance should not silently become a hard gate.

Save per-repeat scores as well as per-fold scores. A pooled row accuracy and an
unweighted fold mean differ when folds differ in size; name which is primary.
Repeated predictions of the same row are dependent observations. Report unique
rows alongside prediction occasions and avoid treating repeated gains as new
independent confirmations. Changing split/metric names does not reset exposure
to the same labels. Harness counts by declared dataset ID cannot detect renamed
or overlapping datasets; preserve that history explicitly in the protocol.

## Define aggregate features operationally

For every count, frequency, normalization, imputation or graph statistic, specify
the reference population and how it is available at prediction time:

- **Inductive:** fit statistics on training covariates, freeze them, transform
  validation/new data with documented unseen-key behavior.
- **Batch-dependent:** use the current prediction batch if that batch is actually
  available. Simulate its construction and size during evaluation; a full labeled
  table and a smaller prediction-only batch are different reference populations.
- **Fixed transductive universe:** use a specified unlabeled universe only when
  permitted and available. Keep its identity constant across evaluation/final
  inference; exclude forbidden labels and post-outcome information.

Test the actual contract on a small fixture before model fits. For an inductive
transform, the same row's features should not change merely because unrelated
prediction rows were added or the batch was chunked. For a batch-dependent
transform, demonstrate expected changes and use the identical policy in CV and
final inference. If peers count across both fitted and prediction populations,
show that explicitly; do not switch to prediction-only counts at the end.

Training label-based neighbor evidence must exclude held-out targets. Define
fallbacks, minimum independent support, conflicts and smoothing. If family,
ticket, device or account keys retrieve the same peer, deduplicate peer IDs or
declare the weighting: two matching keys are not two independent witnesses.
Check key collisions and singleton behavior, not just output shape.

Sources: [scikit-learn evaluation of grouped observations](https://scikit-learn.org/stable/modules/cross_validation.html),
[correlation in CV comparisons](https://scikit-learn.org/stable/auto_examples/model_selection/plot_grid_search_stats.html).
