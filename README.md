# Odium Agent: AI Engineering Nest

An orchestrator that takes a feature request from idea to verified, reviewed code. It runs **Codex CLI** or **Claude Code** as separate subagents, one per step, and checks their work itself: tests must fail before the code exists, pass in a fresh checkout afterwards, and go through an independent review. You approve the plan and decide on the merge.

## How it works

```mermaid
flowchart TD
    you(["You: $build-feature + request"]) --> explore

    subgraph plan_cmd ["plan · read-only"]
        explore["Explorer<br/>map the code and docs"] --> specify["Spec writer<br/>goal, acceptance criteria, questions"]
        specify --> planner["Planner<br/>tasks, test strategy, commits"]
    end

    specify -. questions .-> ask{{"You: answer"}}
    ask -. plan again .-> explore
    planner --> approve{{"You: approve the plan"}}
    approve -. change .-> explore
    approve --> tests

    subgraph run_cmd ["run --from-plan · isolated worktrees"]
        tests["Test engineer<br/>tests that fail first (RED)"] --> red[/"Gate: RED + lint"/]
        red -. lint fails .-> tests
        red --> coder["Coder<br/>make the tests pass"]
        coder --> verify[/"Gate: verify.sh in a fresh checkout"/]
        verify --> review["Reviewer<br/>defects, design vs standards"]
        review -- sensitive paths --> security["Security reviewer<br/>auth, secrets, injection"]
        verify -. fails .-> repair["Coder repair<br/>fix failures and findings"]
        review -. findings .-> repair
        security -. findings .-> repair
        repair --> verify
    end

    review --> result{{"You: result + planned commits"}}
    security --> result
    result -- you say merge --> merge(["Commits as planned, fast-forward merge"])
```

Each box is a separate subagent: its own Codex or Claude process, with its own model and effort per step. Gates are checks the orchestrator runs itself, not an agent. Dotted lines are loops with a fixed budget of attempts. Nothing is pushed: the result is a verified branch on your machine.

## Quick start

Requirements: Python 3.11+, Git, Bash, and the `codex` or `claude` CLI.

```bash
# Install into your project; --local keeps the Nest out of the project's Git history
python /path/to/odium-agent/install.py /your/git/repo --local --template python
```

Then, in the project, start a chat and describe the feature:

- Codex: `$build-feature <what you want>`
- Claude Code: `/build-feature <what you want>`

The chat comes back to you only with questions, with the plan for approval, and with the result.

**Run it in a disposable, credential-free VM or container.** Agents run the code they write; Git worktrees are not a security boundary.

## Documentation

[AI_NEST_README.md](AI_NEST_README.md) covers installation options, verify templates, models per step, limits, gates and the full workflow.
