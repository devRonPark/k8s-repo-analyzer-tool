# Kubernetes Migration Field Assessment Workflow

This file is the canonical runtime-neutral workflow for the Agent Runtime Skill
Package. Runtime adapters may change trigger metadata and command names, but
must not change the workflow rules here.

## Frame

Run a Kubernetes Migration Field Assessment after an application source
repository is available. Act like a Kubernetes field engineer preparing the
first repository-backed migration diagnosis.

The workflow produces a Migration Diagnosis Package from an Evidence Result. It
does not generate manifests, cluster deployment commands, production Secret
values, replica counts, resource sizing, IngressClass, StorageClass, HPA, or PDB
settings.

## Steps

1. Collect a short choice-first analysis start card.
2. Run a cheap repository scan for application candidates and high-value files.
3. Recommend the most likely application target in field-friendly language.
4. Confirm the target and scope with the user.
5. Run the Evidence Core or equivalent repository-backed extraction path.
6. Review the Evidence Result for source-confirmed facts, user input context,
   unknowns, conflicts, and migration risks.
7. Write the Migration Diagnosis Package with an evidence appendix.

## Runtime Adapter Rule

Adapters for specific agent runtimes must refer back to `canonical/` files. They
may not copy and alter no-invention, Secret masking, Evidence Result, or output
rubric rules.
