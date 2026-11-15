---
name: pr-message
description: >-
  Generates a pull request title and description from the current git branch and
  diff. Validates the branch name, maps the branch prefix to a Conventional
  Commits type, and outputs a structured body with Summary, Changes, Related
  PRs, Screenshots, Checklist, Testing, and Issue sections. Use when the user
  explicitly asks to write, draft, or generate a PR description, PR message, or
  pull request message.
disable-model-invocation: true
---

# PR Message Generator

Generate a pull request title and description in English based on the current branch and its
diff against the base branch. Adapted from the Keune `pr-message` skill: same structure, but
GitHub issues instead of Jira tickets, and a privacy check because this repo handles medical data.

## Workflow

```
- [ ] Step 1: Validate the branch name
- [ ] Step 2: Determine the base branch and collect the diff
- [ ] Step 3: Build the PR title
- [ ] Step 4: Ask the user about related PRs
- [ ] Step 5: Build the PR body
- [ ] Step 6: Present the result
```

## Step 1 + 2: Collect all git context in one shell call

Run the following commands together as a single batched shell call — do not split them across
multiple calls:

```bash
git rev-parse --abbrev-ref HEAD
BASE=$(for b in origin/main main; do git rev-parse --verify --quiet "$b" >/dev/null && echo "$b" && break; done)
echo "BASE=$BASE"
git log "$BASE"...HEAD --oneline
git diff "$BASE"...HEAD
```

From the output, extract:
- **Branch name** — validate against the expected format (below)
- **Base branch** — the `BASE=` line (`origin/main` is preferred over a possibly stale local `main`)
- **Commit log** — for context
- **Diff** — the full set of changes

**Branch name format:** `<prefix>/` + optional `<issue number>-` + `<kebab-case description>`

Examples: `feature/settings-window`, `fix/12-initials-left-behind`

Map the prefix to a Conventional Commits type:

| Branch prefix | Type |
|---------------|------|
| `feature/` | `feat` |
| `fix/` or `bugfix/` | `fix` |
| `chore/` | `chore` |
| `refactor/` | `refactor` |
| `docs/` | `docs` |
| `test/` | `test` |

If the branch name does not match the expected format, do not assume the values silently. Show a
corrected branch-name suggestion (for example, `feature/settings-window`) and continue with the
best possible derivation.

## Step 3: Build the PR title

Format: `<type>: name of feature`, or with an issue number: `<type>: name of feature (#12)`

- The description is the kebab-case part of the branch converted to lowercase words separated
  by spaces (without the issue number).
- Breaking change: `<type>!: name of feature` (exclamation mark after the type).
- Never decide a breaking change yourself. Always ask the user to confirm whether this is a
  breaking change before adding the `!`. In this repo a breaking change is, for example, a change
  to the `mijn-gegevens.toml` format that existing users must migrate.

Examples:

```
feature/settings-window          ->  feat: settings window
fix/12-initials-left-behind      ->  fix: initials left behind (#12)
breaking change                  ->  feat!: settings window
```

## Step 4: Ask the user about related PRs

Ask the user whether there are any related pull requests and, if so, which ones. Request a PR link
or `#number` for each, optionally with a short note describing the relation.

- If the user provides one or more related PRs, include the `## Related PRs` section.
- If the user says there are none, remove the `## Related PRs` section entirely.

## Step 5: Build the PR body

Use this template (it matches `.github/pull_request_template.md`):

```markdown
## Summary

<!-- Context of the change, 2-4 sentences. -->

## Changes

- <!-- Bullet points of added/changed/removed features or functionality. -->

## Related PRs

- <!-- Link or #number of a related PR + short note. -->

## Screenshots

| Before | After |
| --- | --- |
|  |  |

## Checklist

- [ ] I've added/updated relevant tests
- [ ] I've added documentation
- [ ] I've checked my own pull request before requesting a review
- [ ] No breaking changes (or confirmed and documented)
- [ ] No real patient data in code, tests, screenshots or this description

## Testing

<!-- How this was tested, e.g. tests/check.py output, app build, manual steps. -->

## Issue

Closes #12
```

Section rules:

- **Summary**: start with the context of the change, 2-4 sentences.
- **Changes**: bullet points describing what was added, changed, or removed.
- **Related PRs**: based on the answer from Step 4. If there are none, remove this section entirely.
- **Screenshots**: only for UI changes (the app window). Keep the `Before`/`After` table with an
  empty row for images the user adds manually. `tests/render_window.py` can render the window.
  Remove this section if not applicable.
- **Checklist**: tests, docs, self-review, breaking changes, and the privacy check. Never tick the
  privacy box on the user's behalf.
- **Testing**: describe how the change was verified. Suggest the relevant commands
  (`.venv/bin/python -I tests/check.py`, `./scripts/build_app.sh`) and ask the user to confirm
  what they actually ran. Do not claim tests passed unless you saw the output.
- **Issue**: `Closes #<number>` when the branch contains an issue number. Never invent issue
  numbers. If there is none, remove this section.

## Step 6: Present the result

Output the title and body together so the user can copy them into the pull request.

## Guidelines

- Keep the Summary concise.
- For `feat` changes, mention the user-facing impact (what the end user sees in the app).
- For `fix` changes, briefly describe the root cause.
- For changes that affect what gets anonymized, mention the effect on `tests/check.py`.
- Remove sections that do not apply (for example, Screenshots for engine-only changes).
- No AI attribution: no `Co-Authored-By` trailer and no "Generated with Claude Code" line. The
  README already mentions that the code was written together with AI. The same format is used
  for commit messages (see CLAUDE.md).
