"""All removal tests run in temporary folders with a fake app registry."""
from pathlib import Path
import argparse
import contextlib
import copy
import hashlib
import json
import os
import stat
import tempfile
import unittest
from unittest import mock
import zipfile
import mystj as m


class FakeRegistry:
    def __init__(self):
        self.data = None

    def values(self):
        return copy.deepcopy(self.data)

    def write(self, values):
        self.data = copy.deepcopy(values)

    def restore(self, before, expected):
        if self.data != expected:
            raise ValueError('Registry changed')
        self.data = copy.deepcopy(before)


@contextlib.contextmanager
def fixture():
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='mystj-test-') as temporary:
        base = Path(temporary).resolve()
        assert base.parent == Path(tempfile.gettempdir()).resolve()
        media, assets = base / 'cd', base / 'tools'
        media.mkdir()
        assets.mkdir()
        (media / 'MYST.DAT').write_bytes(b'fixture Myst data')
        (media / 'QTW').mkdir()
        (media / 'QTW/INTRO.MOV').write_bytes(b'fixture movie')
        manifest = {'files': {p.relative_to(media).as_posix(): {'sha256': m.digest(p), 'size': p.stat().st_size}
                              for p in media.rglob('*') if p.is_file()}}
        for name in (*m.TOOLS, 'MYSTJ-Win11.exe'):
            (assets / name).write_bytes(b'own test tool: ' + name.encode())
        runtime = base / 'runtime.zip'
        with zipfile.ZipFile(runtime, 'w') as archive:
            archive.writestr('scummvm-test/scummvm.exe', b'test interpreter')
            archive.writestr('scummvm-test/COPYING.txt', b'license')
        registry = FakeRegistry()
        with mock.patch.object(m, 'RUNTIME_SHA256', m.digest(runtime)), mock.patch.object(m, 'running_apps', return_value=[]):
            try:
                yield base, media, assets, manifest, runtime, registry
            finally:
                os.chdir(cwd)


def install_fixture(item):
    base, media, assets, manifest, runtime, registry = item
    return m.install(media, base / 'games', runtime, registry, manifest, assets, progress=lambda _: None)


class SetupTests(unittest.TestCase):
    def test_parent_always_gets_mystj_on_different_drives(self):
        for parent in (r'C:\Games', 'D:\\', r'E:\game\emurator\Windows95'):
            self.assertEqual(m.install_target(parent).name, 'MYSTJ')

    def test_existing_mystj_is_not_duplicated(self):
        self.assertEqual(m.install_target(r'E:\Games\MYSTJ'), Path(r'E:\Games\MYSTJ'))

    def test_relative_parent_is_rejected(self):
        with self.assertRaises(ValueError):
            m.install_target('games')

    def test_bad_media_leaves_destination_untouched(self):
        with fixture() as item:
            (item[1] / 'MYST.DAT').write_bytes(b'wrong')
            with self.assertRaises(ValueError):
                install_fixture(item)
            self.assertFalse((item[0] / 'games/MYSTJ').exists())
            self.assertIsNone(item[5].values())

    def test_nonempty_destination_is_never_overwritten(self):
        with fixture() as item:
            root = item[0] / 'games/MYSTJ'
            root.mkdir(parents=True)
            (root / 'precious.txt').write_bytes(b'keep')
            with self.assertRaises(ValueError):
                install_fixture(item)
            self.assertEqual((root / 'precious.txt').read_bytes(), b'keep')

    def test_runtime_checksum_failure_does_not_install(self):
        with fixture() as item:
            item[4].write_bytes(b'corrupt ZIP')
            with self.assertRaises(ValueError):
                install_fixture(item)
            self.assertFalse((item[0] / 'games/MYSTJ').exists())
            self.assertIsNone(item[5].values())

    def test_zip_traversal_is_rejected(self):
        with fixture() as item:
            with zipfile.ZipFile(item[4], 'a') as archive:
                archive.writestr('scummvm-test/../../outside.txt', b'bad')
            with mock.patch.object(m, 'RUNTIME_SHA256', m.digest(item[4])):
                with self.assertRaises(ValueError):
                    install_fixture(item)
            self.assertFalse((item[0] / 'outside.txt').exists())

    def test_copy_and_registration_use_final_path(self):
        with fixture() as item:
            root = install_fixture(item)
            self.assertEqual(root.name, 'MYSTJ')
            self.assertEqual((root / 'data/MYST.DAT').read_bytes(), b'fixture Myst data')
            self.assertIn(str(root), (root / 'userdata/scummvm.ini').read_text(encoding='utf-8'))
            self.assertIn('C+F5 MOUSE_RIGHT', (root / 'userdata/scummvm.ini').read_text(encoding='utf-8'))
            reg = item[5].values()
            self.assertEqual(reg['InstallLocation'][0], str(root))
            self.assertIn('--gui', reg['UninstallString'][0])
            self.assertIn('uninstall', reg['UninstallString'][0])

    def test_keep_preserves_settings_saves_and_added_files(self):
        with fixture() as item:
            root = install_fixture(item)
            (root / 'userdata/saves/mystj.001').write_bytes(b'my save')
            (root / 'notes.txt').write_bytes(b'notes')
            old = (root / 'userdata/scummvm.ini').read_bytes()
            m.uninstall(root, 'keep', item[5])
            self.assertFalse((root / 'data').exists())
            self.assertFalse((root / 'runtime').exists())
            self.assertEqual((root / 'userdata/scummvm.ini').read_bytes(), old)
            self.assertEqual((root / 'userdata/saves/mystj.001').read_bytes(), b'my save')
            self.assertEqual((root / 'notes.txt').read_bytes(), b'notes')
            self.assertTrue((root / m.RETAINED).exists())
            self.assertIsNone(item[5].values())

    def test_full_removes_entire_install_and_registry(self):
        with fixture() as item:
            root = install_fixture(item)
            (root / 'userdata/saves/mystj.001').write_bytes(b'my save')
            (root / 'notes.txt').write_bytes(b'notes')
            m.uninstall(root, 'full', item[5])
            self.assertFalse(root.exists())
            self.assertIsNone(item[5].values())

    def test_keep_and_reinstall_inherits_preferences_and_saves(self):
        with fixture() as item:
            root = install_fixture(item)
            path = root / 'userdata/scummvm.ini'
            path.write_text(path.read_text(encoding='utf-8').replace('fullscreen = false', 'fullscreen = true'), encoding='utf-8')
            (root / 'userdata/saves/mystj.001').write_bytes(b'my save')
            m.uninstall(root, 'keep', item[5])
            root = install_fixture(item)
            self.assertIn('fullscreen = true', (root / 'userdata/scummvm.ini').read_text(encoding='utf-8'))
            self.assertEqual((root / 'userdata/saves/mystj.001').read_bytes(), b'my save')
            m.uninstall(root, 'full', item[5])

    def test_changed_owned_file_is_preserved_in_keep_mode(self):
        with fixture() as item:
            root = install_fixture(item)
            (root / 'data/MYST.DAT').write_bytes(b'user changed file')
            m.uninstall(root, 'keep', item[5])
            self.assertEqual((root / 'data/MYST.DAT').read_bytes(), b'user changed file')

    def test_preview_changes_nothing(self):
        with fixture() as item:
            root = install_fixture(item)
            before = {p.relative_to(root).as_posix(): m.digest(p) for p in m.tree_files(root)}
            reg = item[5].values()
            for mode in ('keep', 'full'):
                m.uninstall_plan(root, mode, item[5])
            self.assertEqual(before, {p.relative_to(root).as_posix(): m.digest(p) for p in m.tree_files(root)})
            self.assertEqual(reg, item[5].values())

    def test_running_game_blocks_removal(self):
        with fixture() as item:
            root = install_fixture(item)
            with mock.patch.object(m, 'running_apps', return_value=['scummvm.exe']):
                with self.assertRaises(ValueError):
                    m.uninstall(root, 'full', item[5])
            self.assertTrue((root / 'data/MYST.DAT').exists())

    def test_changed_registry_blocks_removal(self):
        with fixture() as item:
            root = install_fixture(item)
            item[5].data['InstallLocation'][0] = r'C:\Other\MYSTJ'
            with self.assertRaises(ValueError):
                m.uninstall(root, 'full', item[5])
            self.assertTrue((root / 'data/MYST.DAT').exists())

    def test_readonly_files_can_be_removed(self):
        with fixture() as item:
            root = install_fixture(item)
            (root / 'data/MYST.DAT').chmod(stat.S_IREAD)
            m.uninstall(root, 'full', item[5])
            self.assertFalse(root.exists())

    def test_tampered_manifest_cannot_delete_parent_file(self):
        with fixture() as item:
            root = install_fixture(item)
            outside = root.parent / 'precious.txt'
            outside.write_bytes(b'keep')
            state = json.loads((root / m.STATE).read_text(encoding='utf-8'))
            state['files']['../precious.txt'] = m.digest(outside)
            m.write_json(root / m.STATE, state)
            with self.assertRaises(ValueError):
                m.uninstall(root, 'full', item[5])
            self.assertEqual(outside.read_bytes(), b'keep')

    def test_junction_inside_install_cannot_remove_external_data(self):
        with fixture() as item:
            root = install_fixture(item)
            outside = item[0] / 'outside'
            outside.mkdir()
            (outside / 'precious.txt').write_bytes(b'keep')
            link = root / 'external'
            import subprocess
            # Native PowerShell creates only this named test junction; no shell
            # is used for recursive deletion or file moving.
            script = item[0] / 'junction.ps1'
            script.write_text('param($LinkPath,$TargetPath)\nNew-Item -ItemType Junction -Path $LinkPath -Target $TargetPath -ErrorAction Stop | Out-Null\n', encoding='utf-8')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(script),
                                     '-LinkPath', str(link), '-TargetPath', str(outside)], capture_output=True)
            if result.returncode:
                self.skipTest('Cannot create isolated test junction')
            try:
                with self.assertRaises(ValueError):
                    m.uninstall(root, 'full', item[5])
                self.assertEqual((outside / 'precious.txt').read_bytes(), b'keep')
            finally:
                link.rmdir()

    def test_other_registered_install_blocks_install(self):
        with fixture() as item:
            item[5].data = {'InstallLocation': [r'C:\Other\MYSTJ', 1]}
            with self.assertRaises(ValueError):
                install_fixture(item)
            self.assertFalse((item[0] / 'games/MYSTJ').exists())

    def test_files_added_during_install_are_not_discarded(self):
        with fixture() as item:
            original = m.extract_runtime
            root = item[0] / 'games/MYSTJ'
            def concurrent_change(archive, destination):
                original(archive, destination)
                root.mkdir()
                (root / 'precious.txt').write_bytes(b'keep')
            with mock.patch.object(m, 'extract_runtime', side_effect=concurrent_change):
                with self.assertRaises(ValueError):
                    install_fixture(item)
            self.assertEqual((root / 'precious.txt').read_bytes(), b'keep')
            self.assertIsNone(item[5].values())

    def test_cancel_mode_selection_does_not_delete(self):
        with mock.patch.object(m.sys, 'argv', ['mystj.py', 'uninstall', '--gui']), \
             mock.patch.object(m.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=0), \
             mock.patch.object(m, 'choose_uninstall', return_value=None), \
             mock.patch.object(m, 'uninstall') as remove:
            m.main()
            remove.assert_not_called()

    def test_confirmation_defaults_to_no(self):
        with mock.patch.object(m.ctypes.windll.user32, 'MessageBoxW', return_value=7) as box:
            self.assertFalse(m.message('confirm', confirm=True))
            self.assertTrue(box.call_args.args[3] & 0x100)


def integration(media, runtime_zip, assets):
    registry = FakeRegistry()
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='mystj-cd-test-') as temporary:
        base = Path(temporary).resolve()
        assert base.parent == Path(tempfile.gettempdir()).resolve()
        try:
            with mock.patch.object(m, 'running_apps', return_value=[]):
                root = m.install(media, base, runtime_zip, registry, assets=assets)
                (root / 'userdata/saves/integration.001').write_bytes(b'integration save')
                m.uninstall(root, 'keep', registry)
                assert (root / 'userdata/saves/integration.001').read_bytes() == b'integration save'
                root = m.install(media, base, runtime_zip, registry, assets=assets)
                assert (root / 'userdata/saves/integration.001').read_bytes() == b'integration save'
                m.uninstall(root, 'full', registry)
                assert not root.exists() and registry.values() is None
                print('PASS: real CD -> keep settings -> reinstall -> full removal; registry isolated')
        finally:
            os.chdir(cwd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--media', type=Path)
    parser.add_argument('--runtime-zip', type=Path)
    parser.add_argument('--assets', type=Path)
    args, remaining = parser.parse_known_args()
    result = unittest.main(argv=['test_mystj.py', *remaining], exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.media:
        integration(args.media.resolve(), args.runtime_zip.resolve(), args.assets.resolve())
