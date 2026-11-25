"""Copy only NeetCode 150 solution files from the user's submission repositories.

No dependencies, network requests, or execution of imported solution code.
Run from any directory; source checkouts must be clean Git repositories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.py', '.java', '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.cs',
              '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.rb', '.swift', '.kt',
              '.kts', '.scala', '.dart', '.php', '.sql', '.sh', '.r', '.ex', '.exs'}
REPO_RE = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z')
SLUG_RE = re.compile(r'[a-z0-9][a-z0-9-]*\Z')


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.is_symlink():
        raise ValueError(f'Refusing symlink output: {path}')
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def write_json(path: Path, value) -> bool:
    return write_if_changed(path, (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode())


def load_problems(root: Path):
    problems = read_json(root / 'data/neetcode150.json')['problems']
    if len(problems) != 150 or len({p['id'] for p in problems}) != 150:
        raise ValueError('The allowlist must contain exactly 150 unique problems')
    for p in problems:
        for key in ('id', 'topic_slug', 'leetcode_slug', 'neetcode_slug'):
            if not SLUG_RE.fullmatch(p[key]):
                raise ValueError(f'Unsafe {key}: {p[key]}')
    for key in ('leetcode_slug', 'neetcode_slug'):
        if len({p[key] for p in problems}) != 150:
            raise ValueError(f'Duplicate {key}')
    return problems


def identify(parts: tuple[str, ...], platform: str, problems: list[dict]):
    """Match names, never numeric IDs alone: some LeetHub versions use internal IDs."""
    if platform == 'leetcode':
        if len(parts) != 2:
            return None
        slug = re.sub(r'^\d+-', '', parts[0])
        return next((p for p in problems if p['leetcode_slug'] == slug), None)
    if platform == 'neetcode':
        # Native NeetCode export layout. Do not import other courses or arbitrary folders.
        if len(parts) != 3 or parts[0] != 'Data Structures & Algorithms':
            return None
        return next((p for p in problems
                     if parts[1] in (p['neetcode_slug'], p['leetcode_slug'])), None)
    raise ValueError(f'Unknown platform: {platform}')


def git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(checkout), *args], text=True).strip()


def copy_source(root: Path, checkout: Path, platform: str, repository: str,
                problems: list[dict], provenance: dict) -> tuple[int, list[str]]:
    if not REPO_RE.fullmatch(repository):
        raise ValueError('Invalid source repository')
    if not checkout.is_dir():
        raise ValueError(f'Missing source checkout: {checkout}')
    if git(checkout, 'status', '--porcelain'):
        raise ValueError(f'Source checkout has uncommitted changes: {checkout}')
    commit = git(checkout, 'rev-parse', 'HEAD')
    # ls-files includes only committed files, ignores local scripts, and marks symlinks.
    records = subprocess.check_output(
        ['git', '-C', str(checkout), 'ls-files', '--stage', '-z']).decode().split('\0')
    changed = 0
    candidate_folders, code_folders = set(), set()
    for record in records:
        if not record:
            continue
        meta, relative = record.split('\t', 1)
        mode, blob, stage = meta.split()
        if mode not in ('100644', '100755') or stage != '0':
            continue
        parts = tuple(relative.split('/'))
        problem = identify(parts, platform, problems)
        if not problem:
            continue
        candidate_folders.add(problem['id'])
        source = checkout / relative
        if source.suffix.lower() not in EXTENSIONS or not source.is_file() or source.is_symlink():
            continue
        if not source.resolve().is_relative_to(checkout.resolve()):
            raise ValueError('Source escaped checkout')
        # Read the committed blob to avoid Windows checkout newline conversions.
        content = subprocess.check_output(['git', '-C', str(checkout), 'cat-file', 'blob', blob])
        if not content.strip():
            continue
        content.decode('utf-8')  # Reject binary files disguised as code.
        code_folders.add(problem['id'])
        destination = Path('solutions') / problem['topic_slug'] / problem['id'] / platform / source.name
        target = root / destination
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('Destination escaped repository')
        changed += write_if_changed(target, content)
        digest = hashlib.sha256(content).hexdigest()
        key = destination.as_posix()
        previous = provenance.get(key)
        # Unrelated upstream commits must not create empty sync commits here.
        if not previous or previous['sha256'] != digest or previous['source_path'] != relative:
            provenance[key] = {
                'problem_id': problem['id'], 'platform': platform,
                'source_repository': repository, 'source_path': relative,
                'source_commit': commit, 'source_blob': blob, 'sha256': digest,
                'source_url': f'https://github.com/{repository}/blob/{commit}/{quote(relative, safe="/")}',
            }
    return changed, sorted(candidate_folders - code_folders)


def render(root: Path, problems: list[dict], provenance: dict, sources: dict):
    solutions = {}
    for problem in problems:
        base = root / 'solutions' / problem['topic_slug'] / problem['id']
        entries = []
        for platform in ('leetcode', 'neetcode'):
            directory = base / platform
            if directory.is_symlink():
                raise ValueError('Symlink solution directory')
            if not directory.exists():
                continue
            for path in sorted(directory.iterdir()):
                relative = path.relative_to(root).as_posix()
                info = provenance.get(relative)
                if not info or info['problem_id'] != problem['id'] or info['platform'] != platform:
                    continue
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f'Invalid archived solution: {path}')
                if hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
                    raise ValueError(f'Archived solution differs from provenance: {path}')
                entries.append({'path': relative, 'platform': platform})
        solutions[problem['id']] = entries
        if entries:
            text = [f'# {problem["title"]}', '',
                    f'{problem["topic"]} · {problem["difficulty"]}', '',
                    f'[NeetCode](https://neetcode.io/problems/{problem["neetcode_slug"]}) · '
                    f'[LeetCode](https://leetcode.com/problems/{problem["leetcode_slug"]}/)', '',
                    '## My solutions', '']
            for entry in entries:
                relative = entry['path']
                local = Path(relative).relative_to(base.relative_to(root)).as_posix()
                text.append(f'- [{entry["platform"]}: {Path(relative).name}]({quote(local)}) '
                            f'— [original submission file]({provenance[relative]["source_url"]})')
            write_if_changed(base / 'README.md', ('\n'.join(text) + '\n').encode())
    completed = sum(bool(entries) for entries in solutions.values())
    by_topic = Counter(p['topic'] for p in problems if solutions[p['id']])
    totals = Counter(p['topic'] for p in problems)
    progress = {'completed': completed, 'total': 150,
                'topics': {topic: {'completed': by_topic[topic], 'total': total}
                           for topic, total in totals.items()},
                'problems': [{'id': p['id'], 'completed': bool(solutions[p['id']]),
                              'solutions': solutions[p['id']]} for p in problems]}
    write_json(root / 'data/progress.json', progress)
    lines = ['# NeetCode 150', '', f'**{completed}/150 problems archived**', '',
             'My solutions from LeetCode and NeetCode, restricted to the NeetCode 150 list. '
             'A problem counts once even when solved on both sites. '
             'A checkbox is checked only when actual solution code has been imported.', '',
             '## Automatic sync', '',
             f'- LeetCode: [{sources["leetcode"]}](https://github.com/{sources["leetcode"]}) '
             '(keep using the existing Chrome upload extension).',
             f'- NeetCode: [{sources["neetcode"]}](https://github.com/{sources["neetcode"]}) '
             '(native GitHub integration, auto-commit enabled, Accepted Only).',
             '- GitHub Actions checks both repositories every 30 minutes. Runs can be delayed by GitHub. '
             'For an immediate refresh, open [Actions → Sync NeetCode 150](https://github.com/pingadom/neetcode-150/actions/workflows/sync.yml) '
             'and select **Run workflow**.',
             '- Source solutions are copied verbatim. Only the pinned 150-problem allowlist is imported. '
             'Existing archived solutions are retained if a source file later disappears.',
             '- The count records available solution code from your submission repos; '
             'the sync does not run or independently judge solutions.', '',
             '## Progress by topic', '', '| Topic | Archived |', '|---|---:|']
    lines.extend(f'| {topic} | {by_topic[topic]}/{total} |' for topic, total in totals.items())
    for topic in totals:
        lines += ['', f'## {topic}', '']
        for p in problems:
            if p['topic'] != topic:
                continue
            files = solutions[p['id']]
            mark = 'x' if files else ' '
            title = p['title']
            if files:
                title = f'[{title}](solutions/{p["topic_slug"]}/{p["id"]}/)'
            lines.append(f'- [{mark}] {title} · {p["difficulty"]} · '
                         f'[NC](https://neetcode.io/problems/{p["neetcode_slug"]}) · '
                         f'[LC](https://leetcode.com/problems/{p["leetcode_slug"]}/)')
    lines += ['', '## Maintenance', '',
              'See [SETUP.md](SETUP.md) for sync configuration, historical imports and troubleshooting. '
              '[Problem list and URL mapping](data/neetcode150.json) · '
              '[Import provenance](data/provenance.json) · [Attribution](THIRD_PARTY_NOTICES.md)', '']
    write_if_changed(root / 'README.md', '\n'.join(lines).encode())
    return progress


def synchronize(root: Path, checkouts: dict[str, Path]):
    problems = load_problems(root)
    sources = read_json(root / 'data/sources.json')
    provenance_path = root / 'data/provenance.json'
    provenance = read_json(provenance_path) if provenance_path.exists() else {}
    changed, missing = 0, {}
    for platform, checkout in checkouts.items():
        count, missing[platform] = copy_source(root, checkout, platform, sources[platform], problems, provenance)
        changed += count
    write_json(provenance_path, dict(sorted(provenance.items())))
    progress = render(root, problems, provenance, sources)
    return {'completed': progress['completed'], 'total': 150,
            'solution_files_changed': changed, 'source_folders_without_code': missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--leetcode', required=True, type=Path)
    parser.add_argument('--neetcode', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(synchronize(ROOT, {'leetcode': args.leetcode, 'neetcode': args.neetcode}), indent=2))


if __name__ == '__main__':
    main()
