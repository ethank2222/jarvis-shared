# Jarvis Development Plan

## Product Direction

Jarvis should become a conversational Windows operations assistant, not a collection of exact command phrases.

The target experience is:

- The user describes an outcome in natural language.
- Jarvis understands the intent, asks only necessary questions, and builds a visible plan.
- A local workflow engine executes approved tools in order.
- OpenAI helps interpret, plan, and summarize, but never bypasses local policy or directly controls the computer.
- Jarvis remembers conversational context without silently turning private local data into cloud context.
- Voice is a first-class interface, with typed input as an equal fallback.

## Non-Negotiable Boundaries

1. Microphone audio remains local. Cloud services receive transcribed text only.
2. Every executable capability is represented by a registered local tool.
3. The model may request tools, but `SecurityManager` decides whether they may run.
4. Destructive actions remain blocked until undo and recovery exist.
5. External writes require confirmation or review.
6. Tool arguments are schema-validated before execution.
7. Secrets never enter prompts, history, logs, or tool results.
8. Multi-step plans stop safely on missing information, denial, or failure.

## Target Architecture

```text
voice or typed input
        |
        v
local normalization and fast-path commands
        |
        v
OpenAI intent and planning request
        |
        v
validated workflow plan
        |
        v
SecurityManager -> approval gate -> ActionRegistry
        |                                  |
        +---------- tool results ----------+
                           |
                           v
                 OpenAI final response
                           |
                           v
                 HUD text + ElevenLabs TTS
```

The model is the reasoning layer. The local application remains the execution authority.

## Priority 0: Reliability And Observability

Before adding more autonomy, failures must be understandable.

### Work

- Add provider-specific connectivity checks for OpenAI and ElevenLabs.
- Show the last cloud text and TTS error in the HUD and health report.
- Distinguish authentication, billing, quota, model, network, and playback failures.
- Add structured local logs with request IDs but no prompts or secrets by default.
- Add a diagnostics panel with copyable remediation steps.
- Add startup validation for required settings and configured providers.
- Add a real voice smoke test that verifies generated WAV playback.

### Completion Criteria

- A failed provider never degrades into silence or an unexplained Windows sound.
- `jarvis --health` identifies the failing layer.
- Cloud failures retain a useful local fallback without hiding the original cause.

## Phase 1: One Tool Registry

The current policy list, parser schemas, and action handlers describe tools separately. Replace them with one source of truth.

### Tool Definition

Each tool should define:

- Stable tool name.
- User-facing description.
- Strict JSON input schema.
- Output schema.
- Approval level.
- Privacy flags for cloud text, images, and external writes.
- Timeout and retry policy.
- Idempotency behavior.
- Handler function.
- Examples and evaluation cases.

### Work

- Introduce an `ActionDefinition` registry.
- Generate OpenAI function tools from the registry.
- Generate `SecurityManager` policies from the same definitions.
- Validate every payload before handler dispatch.
- Return typed tool results with `ok`, `data`, `message`, and `error_code`.
- Remove duplicated tool descriptions from the parser and planner.

### Completion Criteria

- A tool cannot be exposed to OpenAI unless it has a local handler and policy.
- Invalid or invented arguments are rejected before execution.
- Tool schemas have contract tests.

## Phase 2: Smarter Command Understanding

Replace regex-only routing with a layered interpreter.

### Layer 1: Local Fast Path

Keep deterministic handling for commands that must be immediate or offline:

- Wake and sleep.
- Help and status.
- Emergency stop or cancel.
- Exact privacy and security controls.
- Common low-risk commands with unambiguous arguments.

### Layer 2: Model Intent Planning

For everything else, send the user text plus approved tool schemas to OpenAI and request a structured plan.

The planner output should include:

- Interpreted goal.
- Ordered steps.
- Dependencies between steps.
- Arguments and references to earlier results.
- Confidence.
- Missing information.
- Whether confirmation is required.
- A short explanation suitable for the HUD.

### Understanding Improvements

- Resolve pronouns and follow-ups such as `it`, `that note`, and `the second file`.
- Parse dates, times, durations, recurrence, and time zones consistently.
- Understand synonyms without adding another regex for each phrase.
- Detect ambiguity and ask one focused clarification question.
- Separate requests from quoted or untrusted content inside documents and email.
- Support corrections such as `No, make that Friday at 3`.
- Keep an offline fallback for core commands when OpenAI is unavailable.

### Evaluation Set

Build a versioned command corpus covering:

- Paraphrases.
- Incomplete commands.
- Ambiguous references.
- Voice transcription errors.
- Prompt injection inside files and email.
- Requests for blocked actions.
- Commands that should remain fully local.

## Phase 3: Real OpenAI Agent Loop

Move from one-shot text answers to a Responses API function-calling loop.

### Execution Loop

1. Send the user request, relevant conversation context, and allowed function tools.
2. Receive zero or more function calls.
3. Validate each function call against the local registry.
4. Apply security and approval policy.
5. Execute approved tools locally.
6. Return structured function outputs to OpenAI.
7. Continue until the model returns a final response or the step limit is reached.

### Guardrails

- Use strict function schemas.
- Limit turns, tool calls, elapsed time, and estimated cost.
- Allow only registered tools for the current interaction.
- Never execute model-produced shell, Python, URLs, or file paths outside approved roots.
- Mark tool results as data, not instructions.
- Require confirmation at the exact point an external mutation would occur.
- Store a redacted trace linking model calls, approvals, tool calls, and results.
- Add a global cancel control checked between every step.

### Responses API State

- Start with local session state and explicit context assembly.
- Optionally use `previous_response_id` for short active conversations.
- Reset state after sleep, privacy mode changes, or a user-requested new conversation.
- Do not persist cloud conversation state indefinitely by default.
- Make context usage visible in the HUD.

## Phase 4: Multi-Action Workflow Engine

Multi-action commands need their own execution model instead of a loop over unrelated results.

### Required Capabilities

- Sequential steps.
- Parallel independent reads.
- References to earlier results.
- Conditions and branching.
- Grouped approval before related writes.
- Partial-failure handling.
- Retry only when an action is safe to repeat.
- Pause, resume, cancel, and inspect.
- Dry-run previews.
- Compensation or undo where supported.

### Example Workflows

`Find my budget notes, summarize the newest one, and create reminders from the action items.`

1. `files.search`
2. Select the newest matching file.
3. `files.summarize` using the selected path.
4. Extract structured action items.
5. Preview reminder drafts.
6. Create approved reminders.

`Check tomorrow's calendar, find a free hour, and draft an email to Sam proposing it.`

1. Read calendar availability.
2. Compute candidate slots locally.
3. Ask for clarification if multiple slots are equally suitable.
4. Draft an email using the selected time.
5. Show the draft for review.

### Plan Data Model

A workflow should contain:

- `workflow_id`
- `goal`
- `status`
- `steps`
- `depends_on`
- `arguments`
- `result_bindings`
- `approval_state`
- `attempt_count`
- `started_at` and `completed_at`
- `failure` and recovery guidance

## Phase 5: Conversational Continuity

Jarvis should understand follow-up turns without pretending to remember everything forever.

### Work

- Add an active conversation session with a clear reset command.
- Track entities introduced during the session.
- Keep tool results available for follow-up references.
- Summarize older turns locally before context grows too large.
- Let the user inspect what context will be sent to OpenAI.
- Separate durable user-approved memory from temporary conversation state.
- Add commands such as `what context are you using?` and `forget this conversation`.

## Phase 6: Context And Personal Intelligence

### Ideas

- Preference-aware answers using only explicitly approved memories.
- Project workspaces that group notes, files, reminders, and conversations.
- A daily briefing assembled from calendar, reminders, and selected email sources.
- Follow-up detection from notes and communications.
- Local semantic search across approved notes and documents.
- Screen context snapshots with explicit capture and expiration.
- Proactive suggestions shown in the HUD but never executed automatically.

## Phase 7: Real Integrations

### Calendar

- OAuth with least-privilege scopes and encrypted tokens.
- Read-only schedule and availability first.
- Event drafts and conflict detection second.
- Confirmed create and update actions last.

### Email

- Read-only search and thread summaries first.
- Draft creation with recipient validation second.
- Sending only through a review screen.
- Treat email content as untrusted data during planning.

### Desktop And Files

- Better approved-folder search with ranking and metadata.
- Safe file previews and result selection.
- Open approved files and applications.
- File moves only after review and with undo metadata.
- Keep arbitrary shell execution blocked.

## Phase 8: Voice Experience

### Work

- ElevenLabs provider health and quota checks.
- Voice selector with a test button and license reminder.
- Stream TTS for lower perceived latency.
- Sentence-level playback while longer responses continue generating.
- Stop speaking immediately when the user says `Jarvis, stop`.
- Avoid reading URLs, stack traces, and large tables verbatim.
- Allow concise spoken responses with full detail retained in the HUD.
- Add local playback device selection and volume controls.

## Phase 9: HUD And Workflow UX

### Ideas

- Show `Understanding`, `Planning`, `Waiting for approval`, `Running`, and `Speaking` states.
- Display the current workflow and active step.
- Let the user edit a proposed plan before execution.
- Provide approve, deny, cancel, retry, and resume controls.
- Add a local activity timeline with redacted inputs and structured results.
- Add provider status indicators for local speech, OpenAI, and ElevenLabs.
- Add settings for privacy, context, budgets, tools, and integrations.

## Phase 10: Testing And Evaluation

### Automated Tests

- Tool schema and policy contract tests.
- Multi-step workflow dependency tests.
- Approval and cancellation tests.
- Prompt-injection and untrusted-data tests.
- Provider error classification tests.
- Conversation reference-resolution tests.
- Golden command-understanding evaluations.
- Mocked OpenAI function-call loop tests.
- Live provider smoke tests behind explicit flags.
- GUI tests for plan review and failure states.

### Metrics

- Correct intent rate.
- Correct tool selection rate.
- Argument accuracy.
- Clarification rate.
- Unsafe plan rejection rate.
- Workflow completion rate.
- Average model calls per completed task.
- Voice response latency.
- Cost per successful workflow.

## Recommended Next Three Milestones

### Milestone A: Agent Foundation

1. Build the unified action registry.
2. Export strict OpenAI function schemas.
3. Add typed tool results and validation.
4. Add a model planner in shadow mode that cannot execute tools.
5. Compare model plans against the local planner on the evaluation set.

### Milestone B: Controlled Tool Loop

1. Implement the Responses function-calling loop.
2. Expose read-only tools first.
3. Return tool outputs to the model for final synthesis.
4. Add step, time, and cost limits.
5. Add trace logging and cancellation.
6. Enable low-risk local writes after approval tests pass.

### Milestone C: Multi-Action Workflows

1. Add workflow persistence and result references.
2. Implement dependent steps and grouped approvals.
3. Ship file-search-to-summary and note-to-reminders workflows.
4. Add pause, resume, retry, and partial-failure UX.
5. Add Calendar read-only tools as the first external integration.

## Explicit Non-Goals For Now

- Arbitrary shell execution.
- Autonomous background actions without a user-visible trigger.
- Cloud microphone streaming.
- Permanent cloud conversation storage by default.
- Email sending without review.
- File deletion.
- Financial transactions.
- Exact imitation of a real person's voice.

## Definition Of Done

A capability is complete only when:

- Its tool contract and policy are registered together.
- Inputs and outputs are validated.
- Privacy impact is documented.
- Approval behavior is tested.
- Failures are visible and actionable.
- The action is auditable without logging secrets.
- Cancellation works.
- Unit and workflow tests pass.
- The README and health diagnostics are current.

## Technical References

- OpenAI function calling: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI conversation state: https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI Responses migration and agentic primitives: https://developers.openai.com/api/docs/guides/migrate-to-responses
- ElevenLabs text-to-speech API: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
