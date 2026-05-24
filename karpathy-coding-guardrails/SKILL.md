---
name: karpathy-coding-guardrails
description: Apply Andrej Karpathy style coding guardrails to implementation tasks. Use when the user wants explicit assumptions, minimal code changes, no speculative abstractions, and clear verification before or during coding work.
---

# Karpathy Coding Guardrails

Use this skill when the task benefits from stricter coding discipline than the default agent behavior, especially for bug fixes, refactors, ambiguous implementation requests, or reviews of proposed changes.

## Core Behavior

### 1. Think Before Coding

- State assumptions that materially affect the implementation.
- If the request is ambiguous and different interpretations would change the code, ask one concise clarifying question instead of guessing.
- Surface simpler alternatives or tradeoffs instead of silently choosing a heavier approach.
- If something still does not make sense after reading the codebase, stop and name the blocker.

### 2. Simplicity First

- Implement the smallest change that fully solves the requested problem.
- Do not add configurability, abstraction layers, or future-proofing unless the request requires them.
- Do not add defensive branches for scenarios that are not realistically reachable in the current code path.
- If the implementation starts growing, trim it back and re-check whether each changed line is necessary.

### 3. Surgical Changes

- Touch only the files and lines needed for the task.
- Match the surrounding code style and local conventions.
- Do not opportunistically refactor neighboring code, reformat unrelated sections, or rewrite comments that are not part of the requested change.
- Remove unused code only when your own change made it unused.
- If you notice unrelated issues, mention them briefly instead of fixing them unprompted.

### 4. Goal-Driven Execution

- Convert the request into explicit success criteria before editing.
- For bug fixes, reproduce the failure first when practical, then verify the fix.
- For behavior changes, prefer adding or updating a targeted test when the repo already has tests for that area.
- End with a concrete verification step such as a focused test command, lint check, or manual validation note.

## Working Pattern

Use this response and execution pattern:

1. Restate the task in one sentence.
2. List any assumptions or note that none are material.
3. State a short plan only if the task has multiple steps.
4. Make the minimum viable code change.
5. Verify with the smallest relevant check.
6. Report exactly what changed and how it was verified.

## Trigger Examples

Use this skill when the user asks for things like:

- "按 Andrej Karpathy 的 CLAUDE.md 风格来改这段代码"
- "先说清楚假设，再做最小改动"
- "不要过度设计，直接修这个 bug"
- "只改必要的地方，并给出验证标准"
