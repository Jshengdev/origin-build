# Dashboard-1 · the root .gitignore silently drops a dashboard fixture, so a fresh clone does not build

**Symptom.** Found in the head's review of #74, 2026-09-27. The import built clean in the clone it was made in, but a real fresh clone of `feat/dashboard-import` failed `tsc`: `lib/data/fixtures.ts(22,19): error TS2307: Cannot find module './fixtures/evals.json'` (and the same in `stories/fixtures.ts`). Of the 152 files at teriyapi/wtdd-remote-v2 92ab4ae, 151 were committed.

**Root cause.** origin-build's root `.gitignore` has a bare `evals.json` (meant for the graded report at the root). A bare name matches at every depth, so `git add dashboard` skipped `dashboard/lib/data/fixtures/evals.json` without a word. The build passed only because the extracted file was still in that clone's working tree.

**Fix (verbatim).** In `dashboard/.gitignore`:
```
!lib/data/fixtures/evals.json
```
then `git add dashboard/lib/data/fixtures/evals.json`.

**Verify.** `git ls-tree -r --name-only <92ab4ae> remote-v2` against `git ls-files dashboard` lists no difference, and a real clone builds: `git clone --branch feat/dashboard-import git@github.com:Jshengdev/origin-build.git /tmp/x && cd /tmp/x/dashboard && pnpm install --frozen-lockfile && pnpm exec tsc --noEmit && pnpm build`.
