import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync', ROOT / 'scripts/sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / 'target'
        (self.target / 'data').mkdir(parents=True)
        for name in ('neetcode150.json', 'sources.json'):
            shutil.copyfile(ROOT / 'data' / name, self.target / 'data' / name)
        self.lc = self.base / 'lc'
        self.nc = self.base / 'nc'
        for directory in (self.lc, self.nc):
            directory.mkdir()
            self.git(directory, 'init', '-q')
            self.git(directory, 'config', 'user.email', 'test@example.invalid')
            self.git(directory, 'config', 'user.name', 'Sync tests')
            self.git(directory, 'config', 'core.autocrlf', 'false')
            self.git(directory, 'config', 'commit.gpgsign', 'false')
            self.git(directory, 'commit', '-qm', 'Empty fixture', '--allow-empty')

    def git(self, directory, *args):
        return subprocess.check_output(['git', '-C', str(directory), *args], stderr=subprocess.STDOUT)

    def add(self, directory, relative, content):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.git(directory, 'add', '.')
        self.git(directory, 'commit', '-qm', 'Fixture')

    def run_sync(self):
        return sync.synchronize(self.target, {'leetcode': self.lc, 'neetcode': self.nc})

    def snapshot(self):
        return {p.relative_to(self.target).as_posix(): p.read_bytes()
                for p in self.target.rglob('*') if p.is_file()}

    def test_allowlist_excludes_other_problems_and_readme_only_folders(self):
        self.add(self.lc, '0001-two-sum/solution.py', b'# my solution\nprint("hi")\n')
        self.add(self.lc, '0009-palindrome-number/solution.py', b'# not on the 150 list\n')
        self.add(self.lc, '0206-reverse-linked-list/README.md', b'No code\n')
        self.add(self.lc, 'Topics/array/template.py', b'# template, not a solution\n')
        result = self.run_sync()
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['source_folders_without_code']['leetcode'], ['0206-reverse-linked-list'])
        files = self.snapshot()
        self.assertFalse(any('palindrome-number' in p or 'template.py' in p for p in files))

    def test_aliases_count_one_problem_across_platforms_and_preserve_code_bytes(self):
        code = '# café\r\nraise RuntimeError("must never execute imported code")\r\n'.encode()
        self.add(self.lc, '0001-two-sum/solution.py', code)
        self.add(self.nc, 'Data Structures & Algorithms/two-integer-sum/submission-0.py', code)
        result = self.run_sync()
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['solution_files_changed'], 2)
        paths = list((self.target / 'solutions').rglob('*.py'))
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(path.read_bytes() == code for path in paths))

    def test_neetcode_only_problem_and_course_boundary(self):
        self.add(self.nc, 'Data Structures & Algorithms/string-encode-and-decode/submission-0.py', b'# my codec\n')
        self.add(self.nc, 'Python For Beginners/two-integer-sum/submission-0.py', b'# unrelated course\n')
        self.assertEqual(self.run_sync()['completed'], 1)
        progress = sync.read_json(self.target / 'data/progress.json')
        solved = [p['id'] for p in progress['problems'] if p['completed']]
        self.assertEqual(solved, ['0271-encode-and-decode-strings'])

    def test_noop_and_unrelated_upstream_commits_do_not_change_outputs(self):
        self.add(self.lc, '0001-two-sum/solution.py', b'# existing\n')
        self.run_sync()
        before = self.snapshot()
        self.assertEqual(self.run_sync()['solution_files_changed'], 0)
        self.assertEqual(before, self.snapshot())
        self.add(self.lc, '0009-palindrome-number/solution.py', b'# unrelated\n')
        self.run_sync()
        self.assertEqual(before, self.snapshot())

    def test_updates_are_copied_but_source_deletions_do_not_erase_archive(self):
        self.add(self.lc, '0001-two-sum/solution.py', b'# old\n')
        self.run_sync()
        self.add(self.lc, '0001-two-sum/solution.py', b'# new\n')
        self.assertEqual(self.run_sync()['solution_files_changed'], 1)
        self.git(self.lc, 'rm', '0001-two-sum/solution.py')
        self.git(self.lc, 'commit', '-qm', 'Removed upstream')
        self.assertEqual(self.run_sync()['completed'], 1)
        self.assertEqual(next((self.target / 'solutions').rglob('*.py')).read_bytes(), b'# new\n')

    def test_empty_source_files_are_not_completed(self):
        self.add(self.lc, '0001-two-sum/solution.py', b' \n')
        self.assertEqual(self.run_sync()['completed'], 0)

    def test_dirty_source_is_rejected(self):
        (self.lc / 'uncommitted.py').write_text('print(1)')
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            self.run_sync()

    def test_invalid_manifest_fails_closed(self):
        path = self.target / 'data/neetcode150.json'
        data = sync.read_json(path)
        data['problems'][0]['neetcode_slug'] = '../outside'
        sync.write_json(path, data)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.run_sync()

    @unittest.skipIf(os.name == 'nt', 'Windows symlinks require extra privileges')
    def test_source_symlinks_are_not_imported(self):
        directory = self.lc / '0001-two-sum'
        directory.mkdir()
        (directory / 'solution.py').symlink_to('/etc/passwd')
        self.git(self.lc, 'add', '.')
        self.git(self.lc, 'commit', '-qm', 'Symlink fixture')
        self.assertEqual(self.run_sync()['completed'], 0)


if __name__ == '__main__':
    unittest.main()
