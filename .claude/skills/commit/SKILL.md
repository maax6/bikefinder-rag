---
name: commit
description: Commit the current work in clean, logical units following this repo's conventions. Use when the user asks to commit (or commit and push).
---

# /commit — commit workflow for bikefinder-rag

## 1. Take stock

Run `git status` and `git diff` (plus `git diff --cached` if anything is
already staged). Understand every change before staging anything.

## 2. Split into logical commits

Group changes by intent, not by file type: one commit per coherent change
(a feature, a fix, a doc update, a dataset). If unrelated changes are mixed
in one file, say so and commit the file where it fits best — never split a
file across commits with partial staging.

## 3. Known exclusions

- `.env` — never. `.env.example` is the committable counterpart.
- `__pycache__/`, `.venv/` — never.
- `data/**/*.jsonl` and anything over 5 MB — only when the user explicitly
  asked to version that dataset.

Eval results (`eval_retrieval_report.json`, `ragas_results*.json`) ARE
committed — repo convention is "results are committed, the cache is not"
(see .gitignore). Commit them with a message stating the corpus they ran on.

A PreToolUse hook (`.claude/hooks/check-commit.sh`) enforces the rules
above: it denies commits containing `.env` and asks the user for files
over 5 MB. If it blocks you, unstage the flagged file — do not work
around the hook.

## 4. Sanity check before committing

For changed Python files: `python3 -m py_compile <files>`. If the change
touches runtime behavior (not just docs/comments), prefer running the
relevant script or a quick smoke test first.

## 5. Message style

Match the existing `git log --oneline` style:

- One imperative English summary line, specific and self-contained
  (e.g. "Resume answer generation per question after an interrupt",
  "Ship the century dataset (1894-1999, all brands, forums uncapped)").
- A short body only when the summary can't carry the why.

## 6. Stage and commit

- Stage explicitly by path: `git add <paths>`. Never `git add -A` or
  `git commit -a`.
- After committing, show `git log --oneline -<n>` for the new commits.
- Push only if the user asked for it.
