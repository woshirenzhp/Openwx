"""Bundle an existing Windows Python/Tk runtime and installed player dependencies.

Run with Python 3.12 x64. No network access or installation is required.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import zipfile
PROJECT = Path(__file__).resolve().parent
PACKAGES = {'numpy': ['numpy', 'numpy.libs'], 'av': ['av', 'av.libs'], 'sounddevice': ['sounddevice.py', '_sounddevice.py', '_sounddevice_data'], 'cffi': ['cffi', '_cffi_backend.cp312-win_amd64.pyd'], 'pycparser': ['pycparser'], 'mido': ['mido'], 'packaging': ['packaging'], 'pillow': ['PIL']}
APP_FILES = ['app.py', 'bootstrap.py', 'engine.py', 'formats.py', 'midi_out.py', 'fonts/UDRGMZtk.ttf', 'song.py', 'smf.py', 'lyrics.py', 'media.py', 'presentation.py', 'timeline.py', 'requirements.txt', 'README.md', 'start_player.cmd', 'start_sample.cmd', 'check_dependencies.py', 'build_portable.py', 'QUICK_START.md', 'localization_manifest.json']

def copy(source, dest):
    if source.is_dir():
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'test', 'tests'))
    else:
        shutil.copy2(source, dest)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--python-root', type=Path, default=Path(sys.base_prefix))
    ap.add_argument('--dependency-dir', type=Path, default=PROJECT.parent / 'analysis_tools')
    ap.add_argument('--zip', type=Path, default=PROJECT / 'MI3_SD3_Sync_Player_Portable_Openjs-wx_0.7_EN.zip')
    ap.add_argument('--repack', action='store_true', help='Package an existing runtime; replace the selected ZIP')
    args = ap.parse_args()
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12) or sys.maxsize <= 2 ** 32:
        ap.error('Build with Windows Python 3.12 x64')
    runtime = PROJECT / 'runtime'
    if not args.repack and (runtime.exists() or args.zip.exists()):
        ap.error('runtime or ZIP already exists; choose a fresh build directory/output')
    root = runtime if args.repack else args.python_root.resolve()
    search = [root / 'Lib' / 'site-packages'] if args.repack else [args.dependency_dir.resolve(), root / 'Lib' / 'site-packages']
    selected = []
    for package, names in PACKAGES.items():
        dist = next((d for base in search for d in importlib.metadata.distributions(path=[str(base)]) if d.metadata['Name'].lower().replace('-', '_') == package), None)
        if dist is None:
            ap.error(f'Missing installed distribution: {package}')
        base = Path(dist.locate_file(''))
        for name in names:
            if not (base / name).exists():
                ap.error(f'Missing dependency: {base / name}')
        metadata = next(base.glob(f'{package}-{dist.version}.dist-info'))
        selected.append((package, dist.version, base, names, metadata))
    required = ['python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt', 'DLLs', 'Lib', 'tcl']
    for name in required:
        if not (root / name).exists():
            ap.error(f'Missing runtime component: {root / name}')
    if not args.repack:
        runtime.mkdir()
        for name in required:
            if name != 'Lib':
                copy(root / name, runtime / name)
        shutil.copytree(root / 'Lib', runtime / 'Lib', ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc', 'test', 'tests', 'idlelib', 'ensurepip', 'turtledemo'))
        (runtime / 'Lib' / 'site-packages').mkdir()
    site = runtime / 'Lib' / 'site-packages'
    versions = {}
    for package, version, base, names, metadata in selected:
        if not args.repack:
            for name in names:
                copy(base / name, site / name)
            copy(metadata, site / metadata.name)
        versions[package] = version
    (runtime / 'python312._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n..\n', encoding='ascii')
    manifest = {'application_version': 'Openjs-wx 0.7 English', 'python': sys.version, 'platform': 'Windows x64', 'packages': versions, 'licenses': 'runtime/LICENSE.txt and runtime/Lib/site-packages/*dist-info/licenses', 'files': {}}
    for path in sorted(runtime.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and (path.suffix != '.pyc'):
            manifest['files'][path.relative_to(PROJECT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = PROJECT / 'portable_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    args.zip.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.zip.with_suffix('.tmp.zip')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in APP_FILES + ['portable_manifest.json']:
            archive.write(PROJECT / name, 'MI3_SD3_Player_EN/' + name)
        for path in sorted(runtime.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and (path.suffix != '.pyc'):
                archive.write(path, 'MI3_SD3_Player_EN/' + path.relative_to(PROJECT).as_posix())
    temporary.replace(args.zip)
    print(json.dumps({'zip': str(args.zip), 'bytes': args.zip.stat().st_size, 'packages': versions}, ensure_ascii=False, indent=2))
if __name__ == '__main__':
    main()
