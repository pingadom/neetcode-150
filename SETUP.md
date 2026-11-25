# How this repository stays up to date

This repository is a filtered archive of your own solutions, with a checklist for exactly 150 problems. It does not contain reference solutions from NeetCode.

## Daily use

1. **LeetCode:** submit as usual in Chrome. Your existing extension uploads accepted solutions to `pingadom/leetcode-solutions`.
2. **NeetCode:** submit while signed into the NeetCode account connected to `pingadom/neetcode-submissions`. In your [profile settings](https://neetcode.io/profile/github), keep **Auto-commit on submission** on and **Accepted Only** selected.
3. **This repository:** GitHub Actions imports matching solutions from both source repositories every 30 minutes (at minutes 13 and 43). GitHub can delay scheduled runs. Use **Actions → Sync NeetCode 150 → Run workflow** for a manual refresh.

The source repositories may contain other problems. The destination only imports the 150 problems in `data/neetcode150.json`. Cross-platform aliases are mapped to the same canonical problem. Multiple languages and NeetCode submission-history files are preserved; each problem counts once.

## Historical submissions

The initial import copied matching solution code already present in your GitHub repositories. A README, a checked box on a practice page, or an empty code file does not count as an archived solution.

For past NeetCode submissions, use **Bulk Sync → Accepted Only → Sync All Now** in NeetCode's GitHub settings. The next run here will pick them up. At initial setup on 2026-11-25, NeetCode reported **No submissions to sync**, and its repository contained only its generated README. Code stored solely in a signed-out browser editor is not an account submission and cannot be recovered from GitHub.

The LeetCode source had a `0206-reverse-linked-list` folder with only a README at initial import. It stays unchecked until an actual solution file appears.

## Repository layout

```text
solutions/<topic>/<canonical-problem>/
  README.md
  leetcode/<original-source-filename>
  neetcode/<original-submission-filename>
data/neetcode150.json   # pinned allowlist and site aliases
data/provenance.json    # original repo, commit, path, blob and SHA-256
data/progress.json      # machine-readable checklist
scripts/sync.py         # importer and README generator
tests/test_sync.py      # meaningful boundary and regression tests
```

Source code is copied byte for byte and never executed. Original commit links are recorded. Identical imports create no new commit. Changed solutions update the archived file and remain available through this repository's Git history. Deleting a source file does not delete the archived copy.

`README.md`, problem READMEs and `data/progress.json` are generated. Put personal explanations in separate `notes.md` files so they survive synchronization.

## Authentication and maintenance

Both source repositories were public at setup. Reading them needs no additional credential; the workflow uses the standard repository-scoped `GITHUB_TOKEN` to commit only to this destination. No personal access token is stored here. If a source is renamed or made private, the workflow will fail visibly instead of silently claiming to sync; update `data/sources.json` and configure a suitably scoped credential if necessary.

The NeetCode 150 list and aliases were checked against NeetCode's published metadata and live site's public problem data on 2026-11-25. They are pinned to avoid unexpected list changes. The importer rejects a list that does not contain exactly 150 unique problems. Update it intentionally if NeetCode revises the list or site aliases.

Run locally with Python 3.10+ and Git:

```sh
git clone https://github.com/pingadom/leetcode-solutions.git .sources/leetcode
git clone https://github.com/pingadom/neetcode-submissions.git .sources/neetcode
python -m unittest discover -s tests -v
python scripts/sync.py --leetcode .sources/leetcode --neetcode .sources/neetcode
```

Source checkouts must be clean. Do not rename or edit generated solution files; edits belong in the originating source repo. The importer verifies archived files against provenance before counting them.

## Verification limits

The tests verify list filtering, renamed-problem matching, duplicate counting, byte preservation, empty/missing code, safe paths, repeat runs, updates, and retention. The sync trusts the source integration's accepted-only setting; it does not rejudge the algorithms. The NeetCode import path is tested with fixtures and should additionally be observed on the first real accepted NeetCode submission.
