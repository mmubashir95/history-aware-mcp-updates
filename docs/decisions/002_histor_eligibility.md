# ADR 002: HISTOR eligibility counting and provenance

## Status

Working decision record for Step 08; research acceptance remains pending.

## Definitions

- A tool is identified by the exact `(serverId, tool name)` pair. Launch
  configuration is additional trajectory evidence, not a replacement identity.
- A distinct definition is the SHA-256 hash of the UTF-8 JSON representation
  of the complete tool object, serialized with sorted keys, compact separators,
  and unescaped Unicode. Missing keys are not replaced by null or empty values.
- Chronological states count recorded state changes in order, including a
  reintroduced definition. They do not imply all real-world states were seen.
- The substantive-state count is the sum of the first known state in each
  observed contiguous segment and each recorded substantive change's known
  after-state. An unknown or broken transition starts a new segment; the count
  does not imply that the segments are connected or that no states were missed.
- The primary target is the latest recorded substantive modification. The
  immediate actual predecessor remains in every window of length two or more;
  earlier context consists of earlier substantive states, with adjacent
  duplicate states omitted. Unknown transitions cannot be bridged.
- A change is substantive unless a documented narrow mechanical rule proves it
  trivial. Schema and hidden-character changes are retained. Significance and
  security labels are not inferred.
- Eligibility is a property of a target window. Clusters, representatives and
  hypothetical concentration caps are separate decisions.

## Implemented operational rules

- Source changes are ordered by `(observedAt, id)` within a server. A same-time
  tie is marked ambiguous. A digest mismatch between adjacent server events is a
  chain break; a verified target pair after a break can remain eligible.
- The only mechanically trivial rule currently recognized replaces a numeric
  token in a standalone description such as `Offers 12 tools.` when every other
  definition field and the rest of the description match. Numeric changes in
  longer descriptions are retained because they may express security limits.
  Hidden-character descriptions and schema changes remain substantive. Other potentially
  cosmetic edits remain substantive or uncertain.
- For package records, launch JSON is canonicalized and hashed per observed
  server/toolset pair. A unique identical recorded configuration is `matching`;
  unique different configurations are `different`; absent or multiple values
  are `unknown`. Known differences block the relevant transition conservatively.
  Unknown launch status is retained as uncertainty, not asserted compatible.
- Structural window references include their source toolset digest, content
  hash, source change ID and before/after side. For k≥3, an earlier substantive
  after-state is retained when trivial edits separate it from the target's
  actual predecessor. Adjacent identical content is not duplicated.
- The version-2 definition index stores offsets and ordinals into the raw
  toolsets file, plus full definition hashes; it does not duplicate tool text.
  Each resolved definition is checked against its indexed identity and hash.
  The configurable in-memory cache is bounded by the total serialized source
  record bytes; decoded Python objects may consume more memory than that bound.
- Exact-history signatures and transitive leakage groups are separate. Groups
  connect histories sharing a selected definition or the same full tool object
  after normalizing numeric tokens in its description. The latter is a broad
  template-similarity proxy for grouping only; it does not classify a revision
  as trivial and can over-group unrelated histories. Representatives are chosen
  deterministically among eligible members before simulated caps are applied.
- WARDEN rescan finding identity uses rule and parsed location; a changed message
  on the same identity is persistent with a changed message. Original HISTOR
  spans are compared separately only where both original scans exist. A missing
  scan is not a clean scan, and neither WARDEN nor LLM output creates labels.
- Selected-state annotation availability is linked only through unambiguous
  extras-change records at the exact server and timestamp. A missing link is
  unknown. An explicitly empty extras digest is distinct from a missing digest.

The present source-type field reflects the current server endpoint. Publisher
values are server-name prefixes, not validated publisher identities. Leakage
groups are an approximation and do not prove statistical independence.

## Open research decisions

Final sample-size requirements, publisher and server caps, maximum experimental
history length and policies for uncertain launch configurations require owner
approval. First observation is not evidence of an original release.
