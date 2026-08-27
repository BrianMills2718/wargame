# Wargame lineages

Wargame is one project with two preserved, unrelated Git histories. They are
different implementation attempts, not branches that should be mechanically
merged.

## Canonical current lineage

- Branch: `main`
- Named snapshot: `lineage/notebook-first-playable-20260827`
- Root commit: `2a5d9c544b499fd941633109ffd5e6f48fd2bcd6`
- Tip before this lineage note: `4e705d733f336bb22b76fa27eeb877c8a1342860`
- Observed commits before this lineage note: 18
- Disposition: active and canonical

This is the notebook-first implementation that evolved into the current
`wargame/` package, CLI, FastAPI/web surface, scenarios, architectural
decisions, and roadmap. New product work starts here unless an explicit future
decision supersedes it.

## Preserved legacy attempt

- Branch: `master`
- Named snapshot: `lineage/autonomous-plan1-rewrite-20260625`
- Root commit: `2bb8fa65eebc60b21ecfeec00310ea57611cb381`
- Tip: `105104fe78e25eef2415356a1bc1a29fa0960e2f`
- Observed commits: 27
- Disposition: abandoned implementation attempt; retained as development
  history and a source of potentially reusable ideas

This lineage is the later autonomous Plan #1 rewrite using a separate
`src/core/` and `src/gm/` architecture. Its own instructions describe Phase 1
as incomplete. It is not the canonical runtime, but its code and reasoning are
not discarded.

## Relationship and operating rule

`git merge-base main master` has no result because the histories have different
root commits. The shared path names do not establish ancestry. Do not use
`--allow-unrelated-histories` merely to make the repository look linear, and do
not rename or delete `master` as cleanup.

The two branches and their annotated lineage tags are the custody mechanism:

- `main` owns current development.
- `master` remains a directly inspectable legacy attempt.
- The tags pin the exact tips reviewed during the 2026-08-27 workspace cleanup.
- Reusing code from `master` means deliberately porting the useful change into
  `main` with provenance, not merging the histories wholesale.

As verified on 2026-08-27, GitHub held both branch tips at the exact revisions
listed above. No local-only commits, data directories, or untracked source
files were found in the canonical checkout.
