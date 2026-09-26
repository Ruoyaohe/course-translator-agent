# Note contract

- Every schedule item has a stable `id`, a `kind`, confirmation status, and zero or more evidence records.
- Evidence refers to an immutable transcript segment and includes its source quote and millisecond range.
- A correction is a distinct item whose `supersedes` field points to the prior item. Retain both statements.
- The mind map is a node list. The service generates Mermaid; agents should not inject raw Mermaid into a draft.
- Publishing writes `课程纪要.md`, `完整原文.md`, and `脑图.mmd`, then updates stable blocks in the schedule and DDL indexes.
- Repeated publication must update the same controlled blocks and must not create duplicate tasks.

