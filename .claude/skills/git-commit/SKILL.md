---
name: git-commit
description: Writes a commit message, commits, and pushes to the remote. Use whenever the user asks to commit (e.g. "commit", "git commit", "commit this", "commit and push", "commit to github").
---

# Git commit

Use this whenever the user asks to commit changes in this repo. Do all of the
following, in order, without stopping to ask permission for each step — the
request to commit is itself the approval for this whole sequence, including
the push at the end.

## 1. Inspect the changes

Run in parallel:
- `git status` — see untracked files (never `-uall`)
- `git diff` — see unstaged changes
- `git diff --cached` — see anything already staged
- `git log --oneline -5` — match this repo's commit message style

## 2. Stage files deliberately

Stage specific files/paths by name — never `git add -A` or `git add .`.
Before staging, check `git status` output for anything that shouldn't be
committed:
- `config.py` must stay untracked (it's gitignored and holds local paths /
  API keys) — if it ever shows as untracked-but-would-be-added, do not add
  it, and flag it to the user.
- Any other file that looks like it might hold secrets or credentials —
  open it and check before staging.

## 3. Write the commit message

Draft a concise commit message (1-2 sentences) from the actual staged diff,
focused on *why* the change was made, not a restatement of the diff.

Pass the message via a heredoc so formatting is preserved:

```bash
git commit -m "$(cat <<'EOF'
<summary line>

<optional body>

EOF
)"
```

If the pre-commit hook (`githooks/pre-commit`) rejects the commit (e.g.
any file changed and its tests fail), stop and report the failure
rather than retrying with `--no-verify`.

Avoid co-author by claude message.

## 4. Push

After a successful commit, push to the tracking remote:

```bash
git push
```

If the current branch has no upstream yet, set one against `origin`:

```bash
git push -u origin <branch>
```

If `git push` fails (no remote configured, auth failure, rejected
non-fast-forward, etc.), report the exact error to the user and ask how to
proceed — do not force-push.

## 5. Confirm

Report the resulting commit hash and confirm it was pushed, in one or two
sentences.
