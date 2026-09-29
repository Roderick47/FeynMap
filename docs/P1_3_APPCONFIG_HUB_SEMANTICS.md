# P1.3 — Preserve AppConfig evidence without building a dependency hub

**Status:** P1.3 accepted against the frozen MDN / Microblog / DRF development corpus. P1.2's five independent MDN facts are unchanged.

## Problem

Before P1.3, the Django adapter generated DEPENDS_ON for every handler in the same source directory as an AppConfig class. On pinned MDN that created 29 handler→AppConfig behavioral dependency edges; DRF had 20. These broad edges affected generic incoming impact, search-neighbor walks, region adjacency and locality scoring. Directory proximity is not evidence that a handler invokes an AppConfig or that editing AppConfig behavior impacts every handler.

## Representation

Remove the synthetic DEPENDS_ON edges rather than merely downweighting them: otherwise graph impact, context navigation and claim validation could continue presenting the unsupported behavioral relationship.

The Django adapter records separate structural observations in graph.metadata['django_app_membership'] with version 1.0.0, relationship 'source_tree_membership_not_behavioral_dependency', associations, and unresolved entries.

Each association records handler node ID, uniquely nearest AppConfig node ID, source directory, handler and AppConfig source paths, scope='source_tree_only', and an EvidenceKind.FRAMEWORK source item with detector django.app_config.source_tree_membership, confidence 0.65 and confidence_tier='inferred'.

Use django_app_memberships(graph, handler_node_id) from feynmap.adapters.frameworks.django to retrieve those structural facts without traversing a behavioral edge. The optional handler filter can be omitted to list all associations.

Metadata survives the multi-language repository merge and SemanticGraph serialization/deserialization, but does not become graph traversal, query terms in region indexes, or an ordinary DEPENDS_ON claim.

**Important:** The association observes source-tree proximity. It does not establish INSTALLED_APPS registration or runtime activity. Nested handlers choose the uniquely nearest configuration; two equally near configurations yield an unresolved record with candidate IDs rather than a guessed membership.

Actual behaviorally evidenced dependencies, model-use, route, template and other edges are not suppressed or reclassified.

## Frozen external acceptance

[GitHub Actions run 36512331939](https://github.com/Roderick47/FeynMap/actions/runs/36512331939). The pinned P1.1a revisions are unchanged.

| Repository | Edges before | Edges after | Synthetic AppConfig dependency edges after | Structural memberships retained |
|---|---:|---:|---:|---:|
| MDN Django Local Library | 635 | 606 | **0** | **29** |
| Django REST Framework | 8,040 | 8,020 | **0** | **20** |
| Flask Microblog | 607 | 607 | 0 | 0 |

All 11 independently authored external probes remain at 7/11 met: MDN 5/6, Microblog 0/2 and DRF 2/3. Remaining named URL, Flask prefix and DRF serializer-context gaps belong to later checkpoints.

An additional real MDN impact gate checks: impact on Book at depth one finds BookListView and BookDetailView through genuine P1.2 USES_DATA edges; impact on CatalogConfig does not fan out to those views solely via membership; and the view region has no direct adjacency to catalog/apps.py through an artificial app-membership edge.

## Tests and compatibility

Local fixtures verify nearest membership, nested configurations, equally-near ambiguity, per-handler inspection, serialization, multi-language merge, model impact, AppConfig non-impact, claim-validation isolation, and no false region-locality hop.

CI now requires MDN=29 and DRF=20 retained source-directory memberships, zero synthetic AppConfig dependency edges, a zero-membership Flask control, five P1.2 graph facts at their correct evidence tier, and real MDN impact/locality correctness. Missing P1.4/P1.5/P2 facts remain visible but do not invalidate this scoped P1.3 gate.

Implementation: feynmap/adapters/frameworks/django.py, feynmap/repository.py, feynmap/p1_external_baseline.py, tests/test_django_app_membership.py, and updated orchestration regression tests.

Permanent machine-readable result: experiments/results/p1_3_20260929_appconfig_hub.json.

**Next:** P1.4 — Django named URL and reverse resolution.
