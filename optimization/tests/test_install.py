import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install_bundle import install


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root/'repo'
        (self.repo/'adapters').mkdir(parents=True)
        (self.repo/'adapters/gateann_adapter.py').write_text('existing')

    def archive(self, names):
        path = self.root/'bundle.tar.gz'
        with tarfile.open(path, 'w:gz') as t:
            for name in names:
                item = tarfile.TarInfo(name)
                item.size = 5
                t.addfile(item, io.BytesIO(b'hello'))
        return path

    def test_install_and_refuse_overwrite(self):
        archive = self.archive(['optimization/a.py', 'scripts/optimization/run.sh'])
        install(archive, self.repo)
        self.assertEqual((self.repo/'optimization/a.py').read_bytes(), b'hello')
        with self.assertRaises(FileExistsError):
            install(archive, self.repo)
        self.assertEqual((self.repo/'adapters/gateann_adapter.py').read_text(), 'existing')

    def test_traversal_and_original_file_are_rejected_before_any_write(self):
        for bad in ['../outside', 'optimization/../../README.md', 'README.md', '/absolute']:
            archive = self.archive(['optimization/good.py', bad])
            with self.assertRaises(ValueError):
                install(archive, self.repo)
            self.assertFalse((self.repo/'optimization/good.py').exists())

    def test_conflict_rejects_whole_bundle_before_write(self):
        (self.repo/'optimization').mkdir()
        (self.repo/'optimization/old.py').write_text('keep')
        archive = self.archive(['optimization/new.py', 'optimization/old.py'])
        with self.assertRaises(FileExistsError):
            install(archive, self.repo)
        self.assertFalse((self.repo/'optimization/new.py').exists())


if __name__ == '__main__':
    unittest.main()
