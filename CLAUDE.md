# CLAUDE.md

## Git workflow

After making changes to this project, always commit and push to GitHub:
1. Stage the changed files (prefer naming specific files over `git add -A`)
2. Commit with a clear message describing the changes
3. Push to `origin main`

Do not leave local changes uncommitted. The project should stay in sync with GitHub.

Note: the local Windows scheduled task (daily Dropbox taste ingestion) commits to the same branch. If you encounter merge conflicts on rebase, they're almost always timestamp-only diffs in `learned_preferences.json`/`.md` — resolve by keeping `HEAD` (the newer remote version).

## Newsletter sources

When adding or troubleshooting a source in `sources.py`:
- The sender address in the dict key **must** match the actual `From:` header in Gmail, not a guess
- Substack newsletters send from `<slug>@substack.com`, not `noreply@<slug>.substack.com`
- Many platforms use subdomains like `@go.fiercepharma.com`, `@email.mckinsey.com`, `@interactive.wsj.com`
- Use `python validate_source.py "keyword"` to discover the real sender address before adding
- Use `python validate_source.py --audit` to check whether existing sources are actually producing emails
