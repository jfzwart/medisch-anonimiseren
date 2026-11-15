# Project conventions

## Commits and pull requests

- No AI attribution in commit messages or PR descriptions: no `Co-Authored-By` trailer and no
  "Generated with Claude Code" line. The repo owner is the only author. The README states once
  that the code was written together with AI.
- Commit messages and PR descriptions use the format of the `pr-message` skill
  (`.claude/skills/pr-message/SKILL.md`, same as `.github/pull_request_template.md`):
  Conventional Commits title, then Summary, Changes, Checklist and Testing sections.
- Never tick the "No real patient data" checklist item without the owner's confirmation.
- Commits use the owner's GitHub noreply address (set in the repo's local git config).

## Language

- Code, comments, docstrings, developer docs and commit/PR text: English.
- Everything the end user sees: Dutch (app UI, messages in `Result`, `mijn-gegevens.toml` and
  its keys, folder and output file names, the user instructions in INSTALL.md).

## Privacy

- Never commit real documents or real personal data. Test data is made up
  (`tests/make_samples.py`, `tests/sample-settings.toml`).
- No network access in the app or at build time: dependencies come only from `wheels/` and
  `build-wheels/` with hashes. A new or updated dependency must be audited first (see README).

## Verifying changes

```bash
.venv/bin/python -I tests/check.py   # end-to-end + leak scan; must print "All good."
./scripts/build_app.sh               # builds dist/Anonimiseren.app and .zip
```

When a change affects what gets anonymized, add a case to `tests/make_samples.py` /
`tests/check.py` and confirm it fails on the old code.
