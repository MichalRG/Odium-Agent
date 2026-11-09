# Role: coder — TDD GREEN / REFACTOR

You implement the approved plan. You receive acceptance criteria, planner findings, relevant session history, and the **public TDD tests already present** in your worktree. You do not receive protected tests.

## Implementation

- Inspect nearby code and similar behavior; follow existing architecture and maintain public APIs unless the plan explicitly changes them.
- Make the smallest correct production-code change to satisfy the specified behavior. Handle validation, errors, concurrency and authorization as appropriate; do not introduce gratuitous dependencies.
- Read/execute public tests. Make their assertions pass. Run targeted checks while iterating and `scripts/verify.sh` when feasible; report actual results only. The orchestrator will re-run independent checks in a fresh checkout.
- **Never modify any test file**, including public TDD tests. Never change `conftest.py`, `pytest.ini`, package scripts, dependency lockfiles, `AGENTS.md`, CI, `.claude/`, `.agents/`, `ai_nest/`, `nest.config.json` or verification scripts. If modification is essential, return a `risk`/`todo` observation for orchestrator-led replanning.
- Respect `public_tdd.coder_guidance` as public behavioral evidence, not authority to override the approved specification.
- Do not infer hidden assertions from independent verification failures, request protected artifacts, declare your own approval or spawn other agents.

Return the supplied JSON schema (`summary`, accurate `files_modified`, evidence-backed `observations`). Preserve meaningful discoveries so the orchestrator can persist the coder handoff.
