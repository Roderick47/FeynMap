# S5.5: bounded tool-schema delivery

`ToolSchemaPacker` converts a sufficient S5.4 routing result into the small
tool catalog delivered to a downstream model. The pack is transport-neutral:
each item carries the grounded tool ID, name, description, input JSON Schema,
read-only flag, contract version, and contract digest.

Delivery follows three constraints:

1. Insufficient and unmatched routes deliver no schemas.
2. Every delivered tool must resolve to the same grounded
   `ToolCapabilitySpace`, with the same contract digest.
3. `max_tools` bounds delivery (default 4) while preserving routing order.

The pack reports the available, selected, and delivered counts separately.
Schemas are defensively copied so downstream payload mutation cannot alter the
grounded capability space.

This checkpoint does not execute tools, translate schemas to a provider-specific
wire format, or benchmark token reduction and routing quality. Those concerns
remain outside S5.5.
