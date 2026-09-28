# AX Experiment v1 frozen hypotheses

These hypotheses are frozen before any held-out execution. They must not be rewritten after held-out results are observed.

## H1

Static Scanner/readiness metrics will be relatively sensitive to structural defects such as duplication, missingness, parseability/accessibility, and measurable staleness.

## H2

Semantic conflict and terminology inconsistency may be weakly represented by Readiness Score v1.

## H3

Relevant single-defect variants are expected to reduce downstream task success relative to Ceiling.

## H4

Static readiness and downstream Agent success are expected to show partial, not perfect, alignment.

## H5

Some apparent retrieval failures may originate from identifier/table discovery rather than semantic retrieval alone.

## Post-freeze rule

The wording above is immutable for `ax-exp-v1`. Any substantive change requires a new experiment version and both compared conditions to be rerun under that version.
