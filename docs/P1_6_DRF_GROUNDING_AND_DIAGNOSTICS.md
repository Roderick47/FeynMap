# P1.6 — DRF source grounding and diagnostic accuracy

**Checkpoint scope:** distinguish source-backed Django REST Framework relations
from name resemblance, and distinguish unmatched integration contracts from
actionable review candidates. All analysis is static. The subject repository's
dependencies are not installed or executed.

## What is grounded

The Django framework pass now runs `django_drf.py` *after* Django named URL
registration. It identifies DRF serializer, ModelSerializer, APIView, generic
view and ViewSet lineages through exact import-qualified class bases, including
source-proven in-repository subclasses. Generic Python analysis remains
framework-neutral.

Source-backed relations:

- An explicit `serializer_class = SomeSerializer` on a proven DRF view
  creates `view --SERIALIZES--> serializer` only if the imported
  in-repository target is unique and a proven serializer.
- An explicit `class Meta: model = SomeModel` creates
  `ModelSerializer --SERIALIZES--> model` only when the serializer is a proven
  model-serializer lineage and the exact in-repository Django model exists.
  Literal Meta fields/exclude/read_only_fields and direct class-body field
  constructors are recorded as declaration evidence, not fabricated
  runtime-generated field nodes. Dynamic expressions remain unresolved.
- Literal `permission_classes` identifies exact imported DRF policies and
  proven local subclasses. A `view --DEPENDS_ON--> permission` edge is
  emitted only for a unique in-repository class; external declared policies
  are recorded as qualified but not invented as repository nodes.
- Route coverage separately lists (a) Django `path`/`re_path` registrations
  already statically proven by P1.4, (b) DRF `router.register()` source
  declarations whose mounting is not proven, and (c) views with no static
  registration proven. **The last category is not proof of an unrouted view
  at runtime.** An unmounted router declaration is not promoted to a real
  `http_server` integration contract.

The pinned DRF implementation contains
`SerializerMetaclass._get_declared_fields`, which imports
`rest_framework.fields.Field` and literally checks `isinstance(obj, Field)`.
P1.6 records one source-evidenced `USES_DATA` edge from that exact method to
that exact field class. This restores a missing real cross-file seam; it does
not link files merely because their names appear in the benchmark oracle.
If the import, AST expression or unique target is absent, no edge is emitted.

All these facts preserve file/line/static evidence, metadata and
snapshot/multilanguage merge semantics. Negative tests cover same-named
unrelated classes, aliased imports, dynamic bindings, custom permission
inheritance, router declarations that are never proven mounted, and missing
core Field checks.

## Diagnostic accounting

The existing `integration.unresolved_contracts` number remains intact as
a *raw count of unmatched contracts*. A new additive
`integration.diagnostics_v2` groups these observations, retaining a sample
and enforcing consistent denominators:

- Available server boundary with no local consumer: normal, not an error.
- Framework intrinsic, including the known built-in Django template-tag
  libraries: not a missing repository edge.
- External address/runtime peer or file I/O without local counterpart:
  no asserted local failure.
- Literal local resource/client/route references with no proven link:
  **review candidates**, not verified bugs.
- Unknown/non-peer contract: preserve uncertainty.

Python parser `unresolved_calls` are counted separately, split into Python
built-ins (e.g. `len`, `isinstance`) versus other unresolved calls.
Framework-specific unresolved dynamic declarations remain separately visible
in their source-layer metadata. Neither group is added to raw unmatched
integration-contract counts.

At the pinned DRF revision
`b578eab1cad040414b758131af1e17aa000b51e2`, the initial P1.6
independent run classified 54 unmatched integration contracts:
**18 review candidates and 36 non-actionable or unproven observations**.
Separately, it identified 1,069 unresolved Python built-in calls in the
generic AST parser. These values are descriptive diagnostics, not an accuracy
score or a declaration that 18 defects exist.

## Acceptance and remaining limitation

The locked external oracle stays unchanged. P1.6 adds a strict replay gate
for the exact `SerializerMetaclass` -> `Field` source relation, both
implementation files appearing in *activated* context, honest diagnostic
denominators, and preservation of all P1.2–P1.5 gates.

Previously, `rest_framework/fields.py` was absent from serializer-query
activation. The source-backed bridge now activates it alongside
`rest_framework/serializers.py`. Under the pre-existing 3,200-token / 24-node
minimal-context packer, the final delivered payload may still omit
`fields.py`. This is explicitly recorded as **activation passed, delivery
still missing**; it is not silently scored as the remaining passing P1.1
probe. The test-vs-implementation context-budget policy is deliberately
deferred to P2, in accordance with the frozen roadmap.

P1.7 should replay all existing source-authored checkpoints without editing
their expectations and assess impact, tier correctness, and diagnostics.
