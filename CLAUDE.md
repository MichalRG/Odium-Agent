# Coding rules


## Definition of done
- A task is done only when `scripts/verify.sh` exits 0. Run it yourself before you say a task is done. Never report a pass you did not see.
- If it fails, report the failing command and its error output exactly. Do not hide a failure or summarize it away.

## How to change code
- Make the smallest change that fully solves the task. Do not add features, options or abstractions that nobody asked for.
- Follow the conventions of the surrounding code: naming, layout, error handling, test style. Reuse existing helpers before you write new ones.
- Ask before you add a dependency.
- Fix the root cause, not the symptom. Before you change a shared function, find all of its callers.
- Write a comment only for the "why" that the code cannot show.

## Tests
- Never delete, skip, weaken or rewrite a test to make it pass. If a test is wrong, say so and explain why.

## Safety
- Never commit secrets, tokens or credentials. Never print them in logs or output.
- Validate input at trust boundaries: HTTP handlers, CLI arguments, files, external APIs.
- Do not change the gates (`scripts/verify.sh`, `.github/workflows/`, `.claude/settings.json`) unless the user asks.
- Do not commit, push, open a PR or deploy unless the user asks. `.claude/settings.json` blocks `git push`.

## Project specifics
<!-- Fill in: the stack, how to run the app, where tests live, and anything an agent cannot find out from the code. -->


## AI Engineering Nest

Read and follow AGENTS.md. Use the provider-independent CLI in AI_NEST_README.md for enforced verification.

In AI Nest runs, only the test engineer writes tests; see AGENTS.md.
