"""Build a patch-only release; product media and ScummVM are never bundled."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from mystj import VERSION

ROOT = Path(__file__).resolve().parent
PUBLIC = ('.gitignore', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'RELEASING.md',
          'CHANGELOG.md', 'Install.cmd', 'Uninstall.cmd', 'mystj.py', 'MYSTJ-Win11.cs',
          'media_manifest.json', 'build_release.py', 'test_mystj.py')


def audit():
    unexpected = []
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if relative.parts[0] in ('.git', '__pycache__', 'build', 'dist'):
            continue
        if path.is_file() and relative.as_posix() not in PUBLIC:
            unexpected.append(relative.as_posix())
    if (ROOT / '.git').exists():
        tracked = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True, check=True).stdout.decode('utf-8').split('\0')
        unexpected += [name for name in tracked if name and name not in PUBLIC]
    if unexpected:
        raise ValueError('公開対象外のファイル: ' + ', '.join(unexpected))
    for name in PUBLIC:
        if not (ROOT / name).is_file() or (ROOT / name).stat().st_size > 150_000:
            raise ValueError('必要なソースまたはサイズを確認できません: ' + name)
    print('PASS: allowlisted source/docs only; no product or runtime binaries')


def build():
    audit()
    output = ROOT / 'build'
    output.mkdir(exist_ok=True)
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
    launcher = output / 'MYSTJ-Win11.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:anycpu', '/optimize+',
                    '/r:System.Windows.Forms.dll', '/out:' + str(launcher), str(ROOT / 'MYSTJ-Win11.cs')], check=True)
    release = ROOT / 'dist'
    release.mkdir(exist_ok=True)
    zip_path = release / f'mystj-win11-patch-{VERSION}.zip'
    prefix = f'mystj-win11-patch-{VERSION}/'
    names = [name for name in PUBLIC if name != '.gitignore']
    sums = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    sums[launcher.name] = hashlib.sha256(launcher.read_bytes()).hexdigest()
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(ROOT / name, prefix + name)
        archive.write(launcher, prefix + launcher.name)
        archive.writestr(prefix + 'SHA256SUMS.json', json.dumps(sums, indent=2) + '\n')
    with zipfile.ZipFile(zip_path) as archive:
        if set(archive.namelist()) != {prefix + name for name in [*names, launcher.name, 'SHA256SUMS.json']} or archive.testzip():
            raise RuntimeError('頒布ZIPを検証できません')
    zip_path.with_suffix('.zip.sha256').write_text(hashlib.sha256(zip_path.read_bytes()).hexdigest() + '  ' + zip_path.name + '\n', encoding='ascii')
    print('Built:', zip_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit', action='store_true')
    audit() if parser.parse_args().audit else build()
