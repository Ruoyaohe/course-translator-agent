---
name: course-interpreter
description: Operate the NTU Course Agent workflow for classroom recording sessions, evidence-backed course notes, mind maps, schedules, and reviewed Obsidian publishing. Use when creating, checking, finalizing, editing, or publishing a course session through the course MCP tools.
---

# Course Interpreter

Use the course MCP tools to manage a session. Audio capture and upload belong to the mobile app; do not send audio through MCP.

## Workflow

1. Create a session only after the user confirms recording permission. Preserve the course title, timezone, languages, and supplied terminology.
2. Read session status rather than repeating finalize calls. Finalize once with a stable idempotency key.
3. Treat live captions as provisional. Use the post-class transcript and evidence timestamps for the final draft.
4. Preserve source segment IDs and timestamps when editing. Mark a date `pending_confirmation` whenever year, date, timezone, or correction is ambiguous. Do not infer a missing deadline.
5. Present the summary, tasks, dates, warnings, and mind map for review. Publish only after explicit approval of that concrete draft.
6. Reuse the same publish idempotency key for uncertain retries. Stop on Git conflicts and leave the draft reviewable.

Read [references/note-contract.md](references/note-contract.md) when changing structured drafts or Obsidian output.

