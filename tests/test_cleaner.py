import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wallpaper_studio.cleaner import run_cleaner


class CleanerTests(unittest.TestCase):
    def test_preview_then_clean_preserves_profile_and_symlink_target(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'home'
            cache = home / '.config/Code/Cache'
            cache.mkdir(parents=True)
            (cache / 'data').write_bytes(b'x' * 8192)
            profile = home / '.config/Code/User'
            profile.mkdir()
            (profile / 'settings.json').write_text('{}')
            outside = Path(root) / 'outside'
            outside.mkdir()
            (outside / 'keep').write_text('important')
            (cache / 'linked').symlink_to(outside, target_is_directory=True)
            with patch('wallpaper_studio.cleaner.subprocess.check_output', return_value=''):
                self.assertIn('Available:', run_cleaner(home=home))
                self.assertTrue((cache / 'data').exists())
                run_cleaner(True, home=home)
            self.assertEqual(list(cache.iterdir()), [])
            self.assertTrue((outside / 'keep').exists())
            self.assertTrue((profile / 'settings.json').exists())

    def test_symlinked_cache_parent_is_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'home'
            home.mkdir()
            external = Path(root) / 'external'
            (external / 'mozilla').mkdir(parents=True)
            (external / 'mozilla/keep').write_text('keep')
            (home / '.cache').symlink_to(external)
            with patch('wallpaper_studio.cleaner.subprocess.check_output', return_value=''):
                run_cleaner(True, home=home)
            self.assertTrue((external / 'mozilla/keep').exists())

    def test_running_code_cache_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            cache = home / '.config/Code/Cache'
            cache.mkdir(parents=True)
            (cache / 'keep').write_text('keep')
            with patch('wallpaper_studio.cleaner.subprocess.check_output', return_value='code\n'):
                self.assertIn('Skipped', run_cleaner(True, home=home))
            self.assertTrue((cache / 'keep').exists())

    def test_migration_checksums_and_idempotence(self):
        spec = importlib.util.spec_from_file_location('migration', Path(__file__).parents[1] / 'tools/migrate-home-storage.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as root:
            source, target = Path(root) / 'source', Path(root) / 'bulk/target'
            source.mkdir()
            (source / 'file').write_text('content')
            (source / 'link').symlink_to('file')
            module.migrate(source, target)
            module.migrate(source, target)
            self.assertTrue(source.is_symlink())
            self.assertEqual((source / 'link').read_text(), 'content')
            self.assertFalse(source.with_name('source.migration-backup').exists())


if __name__ == '__main__':
    unittest.main()
