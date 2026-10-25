"""Patch-only MYST 1.0J setup. Product data is read from the user's CD only."""
from pathlib import Path, PureWindowsPath
import argparse
import csv
import ctypes
import datetime
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import winreg
import zipfile

VERSION = '0.1.0-beta.1'
PRODUCT = 'MYSTJ-Win11-Setup'
TITLE = 'MYST 日本語版 Windows 11 対応化パッチ'
ARP = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\MYSTJ-Win11-Setup'
STATE = 'installation.json'
RETAINED = 'retained-data.json'
ASSETS = Path(__file__).resolve().parent
RUNTIME_VERSION = '2026.4.0'
RUNTIME_URL = 'https://downloads.scummvm.org/frs/scummvm/2026.4.0/scummvm-2026.4.0-win32-x86_64.zip'
RUNTIME_SHA256 = 'fb60cfc0828ed86ef24a60c04b9390676493ab85892d81c56d1de90367d56736'
TOOLS = ('mystj.py', 'Uninstall.cmd', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def writable(path):
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IREAD | stat.S_IWRITE)


def linked(path):
    return path.is_symlink() or bool(path.lstat().st_file_attributes & 0x400)


def check_ancestors(path):
    for item in (path, *path.parents):
        if item.exists() and linked(item):
            raise ValueError('リンクやジャンクションを含む場所は使用できません: ' + str(item))


def safe_path(root, relative):
    name = PureWindowsPath(relative)
    if name.is_absolute() or name.drive or '..' in name.parts or ':' in relative or not name.parts:
        raise ValueError('対象範囲外のパスです: ' + relative)
    result = root.joinpath(*name.parts)
    check_ancestors(result)
    if not result.resolve().is_relative_to(root.resolve()) or result.resolve() == root.resolve():
        raise ValueError('対象範囲外のパスです: ' + relative)
    return result


def tree_files(root):
    check_ancestors(root)
    result, pending = [], [root]
    while pending:
        folder = pending.pop()
        for path in folder.iterdir():
            if linked(path) or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('リンクや対象範囲外のファイルが含まれています: ' + str(path))
            if path.is_dir():
                pending.append(path)
            else:
                result.append(path)
    return result


def install_target(parent):
    """The UI selects a parent; MYSTJ is always appended exactly once."""
    parent = Path(parent).expanduser()
    if not parent.is_absolute() or not parent.drive:
        raise ValueError('保存先をドライブから始まるフルパスで指定してください')
    parent = parent.absolute()
    check_ancestors(parent)
    target = parent if parent.name.casefold() == 'mystj' else parent / 'MYSTJ'
    target = target.resolve()
    forbidden = [Path.home().resolve(), Path(os.environ['LOCALAPPDATA']).resolve(),
                 Path(os.environ.get('WINDIR', r'C:\Windows')).resolve()]
    if any(target == p or p.is_relative_to(target) for p in forbidden):
        raise ValueError('Windowsやユーザーフォルダー全体を導入先にできません')
    return target


class Registry:
    def values(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                result = {}
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name, value, kind = winreg.EnumValue(key, i)
                    if kind not in (winreg.REG_SZ, winreg.REG_DWORD):
                        raise ValueError('既存のアプリ登録形式に対応していません')
                    result[name] = [value, kind]
                return result
        except FileNotFoundError:
            return None

    def write(self, values):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ARP, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            for name, (value, kind) in values.items():
                winreg.SetValueEx(key, name, 0, kind, value)

    def restore(self, before, expected):
        current = self.values()
        if current != expected:
            raise ValueError('アプリ一覧の登録が後から変更されています。削除を止めました')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            for name in current:
                if before is None or name not in before:
                    winreg.DeleteValue(key, name)
        if before is None:
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, ARP, winreg.KEY_WOW64_64KEY)
        else:
            self.write(before)


def registration(root):
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    python = pythonw if pythonw.exists() else Path(sys.executable)
    values = {
        'DisplayName': 'MYST 日本語版（Windows 11対応）', 'DisplayVersion': VERSION,
        'Publisher': 'MYSTJ Windows 11 setup contributors（非公式）',
        'InstallLocation': str(root), 'DisplayIcon': str(root / 'MYSTJ-Win11.exe'),
        'UninstallString': subprocess.list2cmdline([str(python), str(root / 'mystj.py'), 'uninstall', '--target', str(root), '--gui']),
        'InstallDate': datetime.date.today().strftime('%Y%m%d'),
    }
    result = {name: [value, winreg.REG_SZ] for name, value in values.items()}
    result.update({name: [1, winreg.REG_DWORD] for name in ('NoModify', 'NoRepair')})
    return result


def running_apps():
    result = subprocess.run([str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/tasklist.exe'), '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, encoding='oem', errors='replace', check=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    names = {row[0].casefold() for row in csv.reader(result.stdout.splitlines()) if row}
    return sorted(names & {'scummvm.exe', 'mystj-win11.exe'})


def validate_media(media, manifest=None, progress=lambda message: None):
    manifest = manifest or json.loads((ASSETS / 'media_manifest.json').read_text(encoding='utf-8'))
    media = Path(media).resolve()
    progress('CD-ROMの版と読み取りを確認しています…')
    total = len(manifest['files'])
    for index, (name, expected) in enumerate(manifest['files'].items(), 1):
        path = safe_path(media, name)
        if not path.is_file() or path.stat().st_size != expected['size'] or digest(path) != expected['sha256']:
            raise ValueError('対応するMYST 1.0JのCDを選んでください。未対応の版または読み取り不良: ' + name)
        if index % 10 == 0 or index == total:
            progress(f'CD-ROMを確認しています… {index * 100 // total}%')
    return manifest


def fetch_runtime(output, progress=lambda message: None):
    progress('ScummVMを公式サイトから取得しています（約118 MiB）…')
    request = urllib.request.Request(RUNTIME_URL, headers={'User-Agent': 'MYSTJ-Win11-Setup/' + VERSION})
    with urllib.request.urlopen(request, timeout=60) as response, output.open('wb') as stream:
        shutil.copyfileobj(response, stream, 1024 * 1024)
    if digest(output) != RUNTIME_SHA256:
        raise ValueError('ScummVMのSHA-256が一致しません。導入を中止しました')


def extract_runtime(archive_path, destination):
    if digest(archive_path) != RUNTIME_SHA256:
        raise ValueError('対応する公式ScummVM ZIPではありません（SHA-256不一致）')
    with zipfile.ZipFile(archive_path) as archive:
        exe = [i for i in archive.infolist() if PureWindowsPath(i.filename).name.lower() == 'scummvm.exe']
        if len(exe) != 1:
            raise ValueError('ScummVMのZIP構造を確認できません')
        prefix = exe[0].filename[:-len('scummvm.exe')]
        if sum(i.file_size for i in archive.infolist()) > 1_500_000_000:
            raise ValueError('実行環境の展開サイズが想定外です')
        for entry in archive.infolist():
            if not entry.filename.startswith(prefix) or entry.is_dir():
                continue
            relative = entry.filename[len(prefix):]
            if not relative:
                continue
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('ZIP内のリンクは使用できません')
            path = safe_path(destination, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, path.open('wb') as output:
                shutil.copyfileobj(source, output)


def retained_install(root):
    if not root.exists() or not any(root.iterdir()):
        return False
    tree_files(root)
    marker = root / RETAINED
    if not marker.is_file():
        raise ValueError('導入先には既存のファイルがあります。空の保存先を選んでください: ' + str(root))
    value = json.loads(marker.read_text(encoding='utf-8'))
    if value.get('product') != PRODUCT or value.get('root') != str(root):
        raise ValueError('保存済み設定の記録が一致しません')
    if any(p.name not in ('userdata', RETAINED) for p in root.iterdir()):
        raise ValueError('設定以外の残存ファイルがあります。別の保存先を選んでください')
    return True


def initial_settings(root, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'saves').mkdir(exist_ok=True)
    (folder / 'screenshots').mkdir(exist_ok=True)
    path = folder / 'scummvm.ini'
    # Preserve preferences and saved games on reinstall; refresh only our path.
    import configparser
    cfg = configparser.RawConfigParser()
    if path.exists():
        cfg.read(path, encoding='utf-8')
    else:
        cfg['scummvm'] = {'fullscreen': 'false', 'gui_language': 'ja_JP', 'updates_check': '0', 'mute': 'false'}
    if not cfg.has_section('keymapper'):
        cfg.add_section('keymapper')
    if not cfg.has_option('keymapper', 'keymap_global_MENU'):
        cfg.set('keymapper', 'keymap_global_MENU', 'C+F5 MOUSE_RIGHT')
    if not cfg.has_section('mystj'):
        cfg.add_section('mystj')
    for key, value in {'engineid': 'mohawk', 'gameid': 'myst', 'description': 'MYST 1.0J',
                       'language': 'ja', 'platform': 'windows', 'path': str(root / 'data')}.items():
        cfg.set('mystj', key, value)
    with path.open('w', encoding='utf-8') as output:
        cfg.write(output)


def install(media, parent, runtime_zip=None, registry=None, manifest=None, assets=ASSETS, progress=print):
    registry = registry or Registry()
    root = install_target(parent)
    for name in (*TOOLS, 'MYSTJ-Win11.exe'):
        if not (assets / name).is_file():
            raise ValueError('配布ZIPをすべて展開してください。必要なファイルがありません: ' + name)
    if running_apps():
        raise ValueError('MYSTJとScummVMを終了してから導入してください')
    previous = registry.values()
    if previous is not None:
        raise ValueError('既にMYSTJがアプリ一覧に登録されています。先にアンインストールしてください')
    retain = retained_install(root)
    retained_snapshot = ({p.relative_to(root).as_posix(): digest(p) for p in tree_files(root)} if retain else {})
    manifest = validate_media(media, manifest, progress)
    needed = sum(v['size'] for v in manifest['files'].values()) + 1_500_000_000
    ancestor = root.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < needed:
        raise ValueError('インストールには約2.2 GB以上の空き容量が必要です')
    root.parent.mkdir(parents=True, exist_ok=True)
    expected = registration(root)
    # Stage on the destination drive. Product bytes never enter the public repo.
    with tempfile.TemporaryDirectory(prefix='.mystj-setup-', dir=root.parent) as temporary:
        staging = Path(temporary) / 'MYSTJ'
        staging.mkdir()
        archive_path = Path(runtime_zip).resolve() if runtime_zip else Path(temporary) / 'scummvm.zip'
        if runtime_zip is None:
            fetch_runtime(archive_path, progress)
        progress('ScummVMを検証して専用フォルダーへ展開しています…')
        extract_runtime(archive_path, staging / 'runtime')
        progress('CD-ROMのゲームデータをコピーしています…')
        total_bytes = sum(info['size'] for info in manifest['files'].values())
        copied_bytes, last_percent = 0, -1
        for name, info in manifest['files'].items():
            source = safe_path(Path(media).resolve(), name)
            target = safe_path(staging / 'data', name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if digest(target) != info['sha256']:
                raise IOError('コピーしたCDデータの検証に失敗しました: ' + name)
            copied_bytes += info['size']
            percent = copied_bytes * 100 // total_bytes
            if percent != last_percent:
                progress(f'ゲームデータをコピーしています… {percent}%')
                last_percent = percent
        for name in (*TOOLS, 'MYSTJ-Win11.exe'):
            shutil.copyfile(assets / name, staging / name)
        if retain and (root / 'userdata').exists():
            shutil.copytree(root / 'userdata', staging / 'userdata')
            for path in tree_files(root / 'userdata'):
                if digest(path) != digest(staging / 'userdata' / path.relative_to(root / 'userdata')):
                    raise IOError('保存データのコピー確認に失敗しました。元の設定はそのまま残しています')
        initial_settings(root, staging / 'userdata')
        inventory = {p.relative_to(staging).as_posix(): digest(p) for p in tree_files(staging)
                     if p.relative_to(staging).parts[0] != 'userdata'}
        state = {'schema': 1, 'product': PRODUCT, 'root': str(root), 'version': VERSION,
                 'files': inventory, 'registry_before': previous, 'registry_after': expected,
                 'runtime_version': RUNTIME_VERSION, 'phase': 'installed'}
        write_json(staging / STATE, state)
        # A retained installation is moved only inside this checked staging area;
        # its original data is still recoverable if the final rename fails.
        old = Path(temporary) / 'previous'
        check_ancestors(root)
        if retain:
            retained_install(root)
            if retained_snapshot != {p.relative_to(root).as_posix(): digest(p) for p in tree_files(root)}:
                raise IOError('処理中に保存データが変更されました。元の設定を残して導入を中止しました')
        elif root.exists() and any(root.iterdir()):
            raise ValueError('処理中に導入先にファイルが作成されたため上書きできません')
        if root.exists():
            root.rename(old)
        try:
            staging.rename(root)
        except Exception:
            if old.exists():
                old.rename(root)
            raise
        try:
            registry.write(expected)
        except Exception:
            raise RuntimeError('ファイルの配置は完了しましたが、アプリ一覧へ登録できませんでした: ' + str(root)) from None
    progress('完了: ' + str(root / 'MYSTJ-Win11.exe'))
    return root


def load_state(target):
    root = Path(target).absolute()
    check_ancestors(root)
    root = root.resolve()
    if root.name.casefold() != 'mystj' or not root.is_dir():
        raise ValueError('MYSTJのインストール先を指定してください')
    tree_files(root)
    state = json.loads((root / STATE).read_text(encoding='utf-8'))
    if state.get('schema') != 1 or state.get('product') != PRODUCT or state.get('root') != str(root):
        raise ValueError('製品または導入先の記録が一致しません')
    for name in state['files']:
        safe_path(root, name)
    if state['registry_after'] != registration(root):
        # InstallDate and Python executable can change; restrict the set of
        # allowed names/types while retaining the original expected values.
        expected = registration(root)
        if set(state['registry_after']) != set(expected):
            raise ValueError('アプリ登録の記録形式が不正です')
        for name, value in state['registry_after'].items():
            if not isinstance(value, list) or len(value) != 2 or value[1] != expected[name][1]:
                raise ValueError('アプリ登録の記録が不正です')
    return root, state


def uninstall_plan(target, mode='keep', registry=None):
    if mode not in ('keep', 'full'):
        raise ValueError('削除方法が不正です')
    root, state = load_state(target)
    registry = registry or Registry()
    current = registry.values()
    if current is not None and current != state['registry_after']:
        raise ValueError('アプリ一覧の登録が別の導入先または後から変更されています')
    if running_apps():
        raise ValueError('MYSTJとScummVMを終了してからアンインストールしてください')
    remove, preserve = [], []
    for path in tree_files(root):
        name = path.relative_to(root).as_posix()
        if name == STATE:
            continue
        if mode == 'keep' and (name.startswith('userdata/') or state['files'].get(name) != digest(path)):
            preserve.append(name)
        else:
            remove.append(name)
    return {'root': root, 'state': state, 'mode': mode, 'remove': remove, 'preserve': preserve,
            'hashes': {name: digest(safe_path(root, name)) for name in remove}}


def uninstall(target, mode='keep', registry=None):
    registry = registry or Registry()
    info = uninstall_plan(target, mode, registry)
    root, state = info['root'], info['state']
    # Keep scripts and the manifest until data deletion completes, so a locked
    # file does not discard the information needed to retry.
    names = sorted(info['remove'], key=lambda n: (n in ('mystj.py', 'Uninstall.cmd'), n))
    for name in names:
        path = safe_path(root, name)
        if digest(path) != info['hashes'][name]:
            raise IOError('処理中に変更されたファイルがあります。削除を止めました: ' + name)
        writable(path)
        path.unlink()
    if registry.values() is not None:
        registry.restore(state['registry_before'], state['registry_after'])
    if mode == 'keep':
        write_json(root / RETAINED, {'product': PRODUCT, 'root': str(root), 'preserved': info['preserve']})
    writable(root / STATE)
    (root / STATE).unlink()
    for path in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()
    os.chdir(root.parent)
    if not any(root.iterdir()):
        root.rmdir()
    return info


def message(text, confirm=False, error=False):
    flags = 0x10000 | (0x4 | 0x100 | 0x20 if confirm else 0x10 if error else 0x40)
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags) == 6


def choose_install():
    import tkinter as tk
    from tkinter import filedialog, ttk, messagebox
    ui = tk.Tk()
    ui.title(TITLE + ' — インストール')
    ui.geometry('780x390')
    ui.resizable(False, False)
    tk.Label(ui, text='最初にお読みください', font=('', 13, 'bold'), anchor='w').pack(fill='x', padx=20, pady=(16, 6))
    tk.Label(ui, text='選んだ保存先の下に「MYSTJ」フォルダーを自動作成します。\n'
                     '別のドライブを選んでも、必ず MYSTJ フォルダー内へインストールします。\n'
                     'ゲームデータはお手持ちのCDからコピーし、ScummVMは公式サイトから取得します。',
             justify='left', anchor='w').pack(fill='x', padx=20, pady=(0, 14))
    media = tk.StringVar()
    parent = tk.StringVar(value=str(Path(os.environ['LOCALAPPDATA'])))
    destination = tk.StringVar()
    def preview(*unused):
        try:
            destination.set('実際のインストール先: ' + str(install_target(parent.get())))
        except Exception as error:
            destination.set(str(error))
    for label, variable in [('MYST 1.0J CD-ROMのルート', media), ('保存先（MYSTJを自動作成）', parent)]:
        row = ttk.Frame(ui)
        row.pack(fill='x', padx=20, pady=6)
        ttk.Label(row, text=label, width=32).pack(side='left')
        ttk.Entry(row, textvariable=variable, width=48).pack(side='left', fill='x', expand=True)
        def browse(v=variable, title=label):
            folder = filedialog.askdirectory(parent=ui, title=title)
            if folder:
                v.set(folder)
        ttk.Button(row, text='参照', command=browse).pack(side='left', padx=(8, 0))
    parent.trace_add('write', preview)
    ttk.Label(ui, textvariable=destination, wraplength=730).pack(fill='x', padx=20, pady=10)
    ttk.Label(ui, text='必要環境: Python 3.11以降・Windows 11 x64・空き容量 約2.2 GB・インターネット').pack(anchor='w', padx=20)
    result = []
    def accept():
        try:
            if not media.get().strip() or not parent.get().strip():
                raise ValueError('CD-ROMと保存先を指定してください')
            dest = install_target(parent.get())
            retained_install(dest)
            if Registry().values() is not None:
                raise ValueError('既に登録されています。先にMYSTJをアンインストールしてください')
            if not (Path(media.get()) / 'MYST.DAT').is_file():
                raise ValueError('CDのMYST.DATがあるフォルダーを指定してください')
            result.extend([Path(media.get()), Path(parent.get())])
            ui.destroy()
        except Exception as error:
            messagebox.showerror(TITLE, str(error), parent=ui)
    row = ttk.Frame(ui)
    row.pack(side='bottom', fill='x', padx=20, pady=16)
    ttk.Button(row, text='この場所にインストール', command=accept).pack(side='right')
    ttk.Button(row, text='キャンセル', command=ui.destroy).pack(side='right', padx=12)
    preview()
    ui.mainloop()
    return result or None


def choose_uninstall(root):
    import tkinter as tk
    from tkinter import ttk
    ui = tk.Tk()
    ui.title(TITLE + ' — アンインストール')
    ui.geometry('760x300')
    ui.resizable(False, False)
    ttk.Label(ui, text='対象: ' + str(root), wraplength=710).pack(fill='x', padx=20, pady=16)
    mode = tk.StringVar(value='keep')
    ttk.Radiobutton(ui, text='設定・セーブデータを残してアンインストール', variable=mode, value='keep').pack(anchor='w', padx=20)
    ttk.Label(ui, text='userdata内の設定・セーブデータ等を同じMYSTJフォルダーに残します。\n追加・変更されたファイルも保持します。', justify='left').pack(anchor='w', padx=42, pady=(4, 14))
    ttk.Radiobutton(ui, text='完全アンインストール', variable=mode, value='full').pack(anchor='w', padx=20)
    ttk.Label(ui, text='MYSTJフォルダー内の本体・実行環境・設定・セーブデータをすべて削除します。\n削除した保存データは元に戻せません。', justify='left').pack(anchor='w', padx=42, pady=4)
    result = []
    def accept():
        result.append(mode.get())
        ui.destroy()
    row = ttk.Frame(ui)
    row.pack(side='bottom', fill='x', padx=20, pady=16)
    ttk.Button(row, text='次へ', command=accept).pack(side='right')
    ttk.Button(row, text='キャンセル', command=ui.destroy).pack(side='right', padx=12)
    ui.mainloop()
    return result[0] if result else None


def gui_install(media, parent, runtime_zip=None):
    import tkinter as tk
    from tkinter import ttk
    import threading
    import queue
    ui = tk.Tk()
    ui.title(TITLE)
    ui.geometry('650x145')
    ui.protocol('WM_DELETE_WINDOW', lambda: None)
    text = tk.StringVar(value='インストールを開始しています…')
    ttk.Label(ui, textvariable=text, wraplength=610).pack(fill='x', padx=20, pady=20)
    bar = ttk.Progressbar(ui, mode='indeterminate')
    bar.pack(fill='x', padx=20)
    bar.start()
    events = queue.Queue()
    result = []
    def worker():
        try:
            root = install(media, parent, runtime_zip, progress=lambda x: events.put(('text', x)))
            events.put(('done', root))
        except Exception as error:
            events.put(('error', str(error)))
    def poll():
        while not events.empty():
            kind, value = events.get()
            if kind == 'text':
                text.set(value)
            else:
                result.extend([kind, value])
                ui.destroy()
                return
        ui.after(120, poll)
    threading.Thread(target=worker, daemon=True).start()
    ui.after(120, poll)
    ui.mainloop()
    if result and result[0] == 'error':
        raise RuntimeError(result[1])
    return result[1] if result else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--media', type=Path)
    parser.add_argument('--parent', type=Path, help='保存先。末尾にMYSTJを自動追加します')
    parser.add_argument('--target', type=Path)
    parser.add_argument('--runtime-zip', type=Path, help='公式版とハッシュが一致するScummVM ZIPを使用')
    parser.add_argument('--mode', choices=['keep', 'full'])
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            raise ValueError('管理者として実行せず、導入するユーザーの通常権限で実行してください')
        if args.action == 'install':
            if args.gui and not (args.media and args.parent):
                selection = choose_install()
                if selection is None:
                    return
                args.media, args.parent = selection
            if not args.media or not args.parent:
                raise ValueError('--media と --parent を指定してください')
            if args.dry_run:
                validate_media(args.media, progress=print)
                root = install_target(args.parent)
                retained_install(root)
                print('導入予定（変更なし）: ' + str(root))
                return
            root = gui_install(args.media, args.parent, args.runtime_zip) if args.gui else install(args.media, args.parent, args.runtime_zip)
            if args.gui:
                if message('インストールしました。\n' + str(root) + '\n\nMYSTを起動しますか？', confirm=True):
                    subprocess.Popen([str(root / 'MYSTJ-Win11.exe')], cwd=root)
        else:
            target = args.target or ASSETS
            mode = args.mode
            if args.gui and mode is None and not args.dry_run:
                mode = choose_uninstall(target)
                if mode is None:
                    return
            mode = mode or 'keep'
            info = uninstall_plan(target, mode)
            text = ('完全アンインストール' if mode == 'full' else '設定・セーブデータを残すアンインストール')
            text += f'\n対象: {info["root"]}\n削除: {len(info["remove"])} ファイル\n保持: {len(info["preserve"])} ファイル'
            text += '\n\n保存データも削除します。元に戻せません。' if mode == 'full' else '\n\n設定とセーブデータは userdata フォルダーに残ります。'
            if args.dry_run:
                message(text) if args.gui else print(text)
                return
            if args.gui:
                confirmed = message(text + '\n\n実行しますか？', confirm=True)
            else:
                print(text)
                confirmed = args.yes or input('実行する場合は DELETE と入力: ') == 'DELETE'
            if confirmed:
                uninstall(target, mode)
                text = '完全アンインストールしました。' if mode == 'full' else 'アンインストールしました。設定・セーブデータの保存先:\n' + str(info['root'])
                message(text) if args.gui else print(text)
    except Exception as error:
        message(str(error), error=True) if args.gui else print('エラー:', error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
