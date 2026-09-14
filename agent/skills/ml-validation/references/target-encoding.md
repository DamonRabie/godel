# Target-derived feature checks

Outer validation isolation and sound training encodings are separate properties.
Excluding a training row's own target from an aggregate is not sufficient proof
that downstream learning is well behaved. Leave-one-out global priors can create
inverse label patterns for singleton groups despite that exclusion.

Prefer tested inner cross-fitting when generating training target features,
with inner partitions appropriate to entity/time dependence. Validation/test
rows must use maps learned only from the outer training partition. Verify that
smoothing priors, fallback statistics and feature selection obey that boundary.

Useful tests depend on the implementation:

- Singleton and unseen categories, missing groups, and very small partitions.
- Changing held-out labels cannot change the features or model fitted on training.
- Own-label perturbation checks where exclusion is claimed; this alone does not
  test all target-dependent artifacts or downstream behavior.
- High-cardinality noise features do not create misleading apparent training
  performance; inspect how features differ at inference.

If `fit_transform` builds cross-fitted or leave-one-out representations while
`transform` uses full fitted maps, `pipeline.score(training_data)` does not score
the representation used to fit the downstream model. Do not compare that score
with validation to diagnose ordinary overfitting. Inspect the appropriate
training representation or rely on held-out predictions for comparison.

Document the algorithm and tests precisely: leave-one-out is not inner K-fold
cross-fitting. [scikit-learn's target-encoder example](https://scikit-learn.org/stable/auto_examples/preprocessing/plot_target_encoder_cross_val.html)
illustrates why the training representation matters.
