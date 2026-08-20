# AGENTS

## MUST

- **Code:** production-ready for what you touch; repo conventions; no stray
  debug or unfinished paths unless the task requires them.
- **Text in tree** (Markdown, comments, specs, docs, examples, `CHANGELOG`,
  **commit bodies**): write for a third party. Contracts, invariants, and how
  to run or extend only. No chat context, narration, reasoning, process, or
  padding.
  Imperative or neutral third person. PR/issue material stays in PRs/issues.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/);
  imperative subject only. Body only for several distinct changes: `-` bullets,
  one per line, no subject restatement; body text obeys the rules above.
  If signing fails, abort; do not retry it unsigned.

## Tools

- Hooks: `prek` (not `pre-commit`). Staged work: `prek run <hook-id>`.
- Workspace commands: `mise` (not `package.json` scripts or a Makefile at the
  repo root).
- Apt packages: persist only via `common-utils` in
  `.devcontainer/devcontainer.json`. No one-off packages there.

## Scope

- No unrelated refactors. Prefer hooks/formatters; broad hand-format only if
  asked. Beyond staged: one hook at a time,
  `prek run <hook-id> --all-files` (not `prek run --all-files` on the whole
  tree unless needed).

## Security

- No secrets in the tree; env, secret stores, or untracked local config only.
- Prefer maintained dependencies; skip opaque or abandoned ones.
- No hardcoded sensitive values anywhere (tests, fixtures, examples included):
  placeholders, fakes, or runtime injection only.
