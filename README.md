# Reuse Research

An agent skill that researches existing GitHub projects before you build: **adopt a dependency, extend a whole application, study another implementation, or build the remaining gaps.**

[![Tests](https://github.com/zeekayzeekay/reuse-research/actions/workflows/test.yml/badge.svg)](https://github.com/zeekayzeekay/reuse-research/actions/workflows/test.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## The problem

Coding agents can start implementing too quickly. A useful library might already solve a subtask, a whole application might be a better starting point, or another implementation might reveal failure cases the plan missed. A shortlist of popular repositories alone does not answer those questions.

Reuse Research gives the agent a research workflow closer to an experienced developer's: discover broadly, investigate the strongest options, compare ownership and integration costs, and bring the findings back into the implementation plan.

Repositories in other languages and frameworks remain useful. Compatibility affects whether you can adopt their code; their design, supported use cases and failure handling can still inform your own implementation.

## Install

With Node.js/npm available, install through the [Skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add zeekayzeekay/reuse-research --skill reuse-research
```

The interactive installer lets you choose agents and installation scope. For a global installation for Codex and Claude Code:

```bash
npx skills add zeekayzeekay/reuse-research --skill reuse-research --agent codex claude-code --global
```

Add `--copy` if you prefer independent copies or symlinks are unavailable. To inspect the repository's available skills before installing:

```bash
npx skills add zeekayzeekay/reuse-research --list
```

Updates are available through:

```bash
npx skills update reuse-research --global
```

This repository follows the installable `skills/<name>/SKILL.md` layout. [skills.sh](https://skills.sh/docs/faq) tracks directory listings through installation telemetry; GitHub publishing and directory indexing are separate.

### Manual installation

Clone the repository and copy the **complete** `skills/reuse-research` directory, including its scripts, references and attribution, into your agent's skills directory. For example, global installations use `~/.codex/skills/reuse-research` for Codex or `~/.claude/skills/reuse-research` for Claude Code. Reload the agent's skill discovery if required by that client.

### Requirements

- A coding agent that supports skills and can search/read public sources.
- **Python 3.11+** for the bundled helpers; they use the standard library only.
- **GitHub CLI (`gh`)** is optional. The search helper uses existing `gh` access when installed, or the anonymous public GitHub API otherwise. If `gh` is installed, authenticate it before using the helper; failed access is recorded as a gap.
- **Node.js/npm** is needed for the Skills CLI installer, not for the Python helpers.

No extra model API, paid search service, backend or MCP server is required. The host agent supplies source reading and judgments. Without Python, it can keep equivalent records using its own tools and disclose that fallback.

## Use

In Codex, Claude Code or another skill-capable agent, ask it to use the `reuse-research` skill. Include your goal and any constraints that matter. For example:

```text
Use the reuse-research skill to research a YouTube/Instagram knowledge extractor.
Cover captions, reels, mixed-media carousels, metadata and recoverable ingestion.
Consider whole extractors and reusable components, including implementations
in other stacks. Save the findings and revise our plan before writing code.
```

The agent reads relevant project context and infers the stack. You can specify a report location, a read-only project, a time budget, or questions to prioritize.

To encourage use before substantial implementation, add this to your project's agent instructions:

```text
Before substantial feature implementation, dependency selection or replacement,
or an unfamiliar integration, use the reuse-research skill and reconcile the
implementation plan with its findings. Skip cosmetic changes and routine fixes;
honor explicit requests to bypass research.
```

Automatic invocation depends on the host agent. The skill's metadata enables normal discovery; it does not enforce a research gate.

## What it does

1. **Find whole solutions first.** Start with ordinary task-keyword searches and primary documentation before narrowing the problem to components.
2. **Protect promising alternatives.** Keep a small source-bound whole-solution shortlist through later searches, briefing and ranking. Each option gets an assessment and a next check, including deferred options.
3. **Cover missing capabilities.** Research subtasks, adjacent terminology and underlying libraries without restricting the pool to the current stack.
4. **Inspect selectively.** Read relevant docs, code and tests for behavior that could change adoption, architecture or implementation. Separate documented claims, source inspection and executed tests.
5. **Revise the plan.** Compare whole-app adaptation with component composition; transfer observed cases and retain consequential unknowns.

## What you get

A Markdown report in `.reuse-research/` or your chosen location, with:

- Requirement-specific decisions: `USE`, `ADAPT`, `CONTRIBUTE`, `FORK`, `STUDY`, `BUILD` or `DEFER`.
- A comparison of whole solutions, complementary components and ownership costs.
- Source links, revisions where available, evidence limits and integration obstacles.
- Observed input/failure cases and proposed checks for your implementation.
- A revised implementation plan and explicit deferred decisions.

When helpers are used, the run also retains structured discovery, evidence and accounting artifacts for replay. Those artifacts validate provenance and visibility; relevance and suitability remain agent judgments.

Default targets are 5–10 minutes for an ordinary feature, or 20 minutes for broad research with the last four minutes reserved for reporting. Budgets are configurable targets, not a background hard-stop timer.

## Status and limitations

**v0.6.1 is an advisory release.** The 84 offline checks validate helper invariants. Realistic pilots produced useful comparisons and implementation cases, while also exposing missed repositories and timing overruns. Candidate runtime and integration require validation in your environment. See [validation notes](docs/VALIDATION.md) for the evidence boundaries.

The skill researches before implementation. Installing it does not authorize cloning and executing arbitrary candidate programs, changing project files, or performing external actions beyond your task's scope.

## Development

```bash
git clone https://github.com/zeekayzeekay/reuse-research.git
cd reuse-research
python -m unittest discover -s tests -p "test_reuse*.py" -v
```

Tests are offline and use synthetic fixtures. [Contributing](CONTRIBUTING.md) explains how to report a retrieval miss or improve the workflow. Helper schemas and commands live in the [skill references](skills/reuse-research/references/discovery-cli.md).

## License and attribution

MIT. The workflow adapts GitHub Community Spain's [github-build-or-reuse](https://github.com/ghspain/github-build-or-reuse). Its copyright and terms are preserved; see [LICENSE](LICENSE) and the [package attribution](skills/reuse-research/NOTICE.md). Other reviewed repositories informed research; their code is not bundled.
