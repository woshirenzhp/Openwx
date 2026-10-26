"""Versioned, language-neutral project documents and streamed resource archives."""
from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path
import hashlib
import json
import math
import os
import re
import shutil
import stat
import uuid
import zipfile
FORMAT = 'openjs-wx-project'
SUFFIXES = {'.opw': 'references', '.opx': 'packed', '.mi3proj': 'references', '.mi3pack': 'packed'}

def number(value, low=0, high=float('inf')):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (not math.isfinite(value)) or (not low <= value <= high):
        raise ValueError('Invalid numeric project setting')
    return value

def validate(data):
    from lyrics import Cue
    from timeline import TimelineModel
    from media import Style
    from PIL import ImageColor
    if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1:
        raise ValueError('Unsupported project format or version')
    if data.get('kind') not in SUFFIXES.values() or not re.fullmatch('[0-9a-f]{32}', data.get('project_id', '')):
        raise ValueError('Invalid project header')
    resources = data['resources']
    if not isinstance(resources, list) or len(resources) > 4096:
        raise ValueError('Invalid project resource list')
    ids = set()
    for item in resources:
        rid = item['id']
        if not re.fullmatch('r[0-9]+', rid) or rid in ids:
            raise ValueError('Invalid or duplicate project resource identifier')
        ids.add(rid)
        if not isinstance(item['path'], str) or not isinstance(item['name'], str):
            raise ValueError('Invalid project resource path')
        number(item['size'])
        if data['kind'] == 'packed':
            if not re.fullmatch('assets/r[0-9]+/[^/\\\\:\\x00-\\x1f]+', item['path']) or item['path'].split('/')[-1] in ('.', '..'):
                raise ValueError('Unsafe packed resource path')
            if not re.fullmatch('[0-9a-f]{64}', item['sha256']):
                raise ValueError('Invalid resource digest')
    links = data['links']
    if not isinstance(links['music'], list):
        raise ValueError('Invalid music links')
    for rid in links['music'] + [links[k] for k in ('audio', 'visual', 'font') if links[k] is not None]:
        if rid not in ids:
            raise ValueError('Unresolved project resource identifier')
    for row in data['lyrics']:
        cue = Cue(**row)
        if not isinstance(cue.text, str):
            raise ValueError('Invalid lyric text')
        TimelineModel.validate(cue)
    settings = data['playback']
    if settings['mode'] not in ('auto', 'mix', 'audio', 'midi'):
        raise ValueError('Invalid playback mode')
    if not isinstance(settings['variant'], int) or settings['variant'] < 0:
        raise ValueError('Invalid music resource index')
    number(settings['audio_offset'], -86400, 86400)
    number(settings['midi_offset'], -10, 10)
    number(settings['master'], 0, 1)
    for gain in settings['gains']:
        number(gain, 0, 1)
    if len(settings['midi_devices']) != 4 or len(settings['midi_sources']) != 4 or any((v not in (0, 1) for v in settings['midi_sources'])):
        raise ValueError('Project needs four MIDI output settings')
    for desc in [settings['audio_device']] + settings['midi_devices']:
        if desc is not None and (not isinstance(desc, dict) or not isinstance(desc['name'], str) or (not isinstance(desc['id'], int))):
            raise ValueError('Invalid device descriptor')
    for variant, routes in settings['routes'].items():
        if not variant.isdecimal():
            raise ValueError('Invalid variant routing index')
        for track, ports in routes.items():
            if not track.isdecimal() or not isinstance(ports, list) or any((type(p) != int or p not in range(4) for p in ports)):
                raise ValueError('Invalid project track routing')
    p = data['presentation']
    style = p['style']
    known = {f.name for f in fields(Style)} - {'font'}
    if set(style) != known:
        raise ValueError('Invalid project style fields')
    for key in ('color', 'highlight', 'stroke', 'background'):
        ImageColor.getrgb(style[key])
    for key, low, high in [('size', 8, 200), ('stroke_width', 0, 12), ('bottom', 0, 500), ('page_lines', 1, 4)]:
        number(style[key], low, high)
        if type(style[key]) != int:
            raise ValueError('Invalid integer style setting')
    for key in ('advance_ms', 'hold_ms', 'fade_in_ms', 'fade_out_ms', 'max_advance_ms'):
        number(style[key], 0, 60000)
        if type(style[key]) != int:
            raise ValueError('Invalid timing style')
    for key in ('immediate_line_change', 'timing_enabled', 'fill_early'):
        if type(style[key]) != bool:
            raise ValueError('Invalid style flag')
    if style['timing_enabled'] and style['fill_early'] and (style['max_advance_ms'] < style['advance_ms']):
        raise ValueError('Invalid lyric lead times')
    number(p['lyric_offset'], -60, 60)
    number(p['video_offset'], -60, 60)
    number(p['duration'], 0.001, 86400)
    number(data['position'])
    number(p['local_position'])
    if p['resolution'] not in ('640x360', '1280x720', '1920x1080') or p['fps'] not in (24, 25, 30):
        raise ValueError('Invalid project export size or frame rate')
    if p['output_format'] not in ('mp4', 'prores4444') or p['audio'] not in ('none', 'video', 'mix'):
        raise ValueError('Invalid project export format')
    for key in ('follow', 'enable_preview', 'enable_export', 'filter_numeric', 'green_export', 'panel_open'):
        if type(p[key]) != bool:
            raise ValueError('Invalid presentation flag')
    if not isinstance(p['previews'], list) or len(p['previews']) > 2 or any((type(v) != bool for v in p['previews'])):
        raise ValueError('Invalid preview list')
    return data

def relative(path, parent):
    try:
        return os.path.relpath(path, parent)
    except ValueError:
        return str(path)

def write(path, snapshot, paths, progress=lambda message: None):
    path = Path(path).resolve()
    kind = SUFFIXES.get(path.suffix.lower())
    if kind is None:
        raise ValueError('Use .opw or .opx')
    if any((path == Path(value).resolve() for value in paths.values())):
        raise ValueError('Project cannot overwrite a linked resource')
    data = deepcopy(snapshot)
    data.update(format=FORMAT, version=1, kind=kind, project_id=uuid.uuid4().hex)
    resources = []
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) if kind == 'packed' else open(temporary, 'wb') as out:
            for original in data['resources']:
                rid = original['id']
                source = Path(paths[rid]).resolve()
                before = source.stat()
                if not source.is_file():
                    raise ValueError('Not a regular resource file: ' + str(source))
                item = {'id': rid, 'name': source.name, 'size': before.st_size, 'builtin_font': bool(original.get('builtin_font', False))}
                if kind == 'packed':
                    item['path'] = 'assets/' + rid + '/' + source.name
                    digest = hashlib.sha256()
                    progress('Packing: ' + source.name)
                    with source.open('rb') as inp, out.open(item['path'], 'w', force_zip64=True) as target:
                        for block in iter(lambda: inp.read(1024 * 1024), b''):
                            digest.update(block)
                            target.write(block)
                    item['sha256'] = digest.hexdigest()
                else:
                    item.update(path=relative(source, path.parent), absolute_path=str(source), mtime_ns=before.st_mtime_ns)
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Resource changed while saving: ' + str(source))
                resources.append(item)
            data['resources'] = resources
            validate(data)
            raw = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
            if kind == 'packed':
                out.writestr('manifest.json', raw, compress_type=zipfile.ZIP_DEFLATED)
            else:
                out.write(raw)
        temporary.replace(path)
        return data
    finally:
        if temporary.exists():
            temporary.unlink()

def read(path, progress=lambda message: None, cache_root=None):
    path = Path(path).resolve()
    kind = SUFFIXES.get(path.suffix.lower())
    if kind is None:
        raise ValueError('Use .opw or .opx')
    if kind == 'references':
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Project manifest is too large')
        data = validate(json.loads(path.read_text('utf-8-sig')))
        if data['kind'] != kind:
            raise ValueError('Project kind does not match its extension')
        paths = {}
        for item in data['resources']:
            candidates = [path.parent / item['path'], Path(item.get('absolute_path', '')), path.parent / item['name']]
            found = next((p.resolve() for p in candidates if p.is_file()), None)
            if found:
                paths[item['id']] = found
        return (data, paths)
    parent = Path(cache_root) if cache_root else Path(__file__).parent / 'project_cache'
    parent.mkdir(parents=True, exist_ok=True)
    root = None
    created = False
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set((n.casefold() for n in names))) or len(names) > 4097:
                raise ValueError('Duplicate or excessive archive members')
            manifest = archive.getinfo('manifest.json')
            if manifest.file_size > 32 * 1024 * 1024:
                raise ValueError('Project manifest is too large')
            raw = archive.read(manifest)
            data = validate(json.loads(raw.decode('utf-8-sig')))
            if data['kind'] != 'packed':
                raise ValueError('Not a packed project')
            expected = {'manifest.json'} | {r['path'] for r in data['resources']}
            if set(names) != expected:
                raise ValueError('Unexpected packed project members')
            for item in data['resources']:
                info = archive.getinfo(item['path'])
                if info.file_size != item['size'] or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('Invalid resource size or symlink')
            root = parent / (data['project_id'] + '_' + hashlib.sha256(raw).hexdigest()[:16])
            if root.is_dir():
                cached = {}
                valid = True
                for item in data['resources']:
                    candidate = (root / item['path']).resolve()
                    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file() or candidate.stat().st_size != item['size']:
                        valid = False
                        break
                    digest = hashlib.sha256()
                    with candidate.open('rb') as inp:
                        for block in iter(lambda: inp.read(1024 * 1024), b''):
                            digest.update(block)
                    if digest.hexdigest() != item['sha256']:
                        valid = False
                        break
                    cached[item['id']] = candidate
                if valid:
                    return (data, cached)
                root = parent / uuid.uuid4().hex
            if sum((i.file_size for i in infos)) > shutil.disk_usage(parent).free:
                raise ValueError('Not enough space to extract project resources')
            root.mkdir()
            created = True
            paths = {}
            for item in data['resources']:
                info = archive.getinfo(item['path'])
                if info.file_size != item['size'] or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('Invalid resource size or symlink')
                target = (root / item['path']).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError('Unsafe resource path')
                target.parent.mkdir(parents=True, exist_ok=True)
                progress('Extracting: ' + item['name'])
                digest = hashlib.sha256()
                with archive.open(info) as source, target.open('xb') as out:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(block)
                        out.write(block)
                if digest.hexdigest() != item['sha256']:
                    raise ValueError('Resource checksum mismatch: ' + item['name'])
                paths[item['id']] = target
            return (data, paths)
    except Exception:
        if created and root.is_dir() and (root.resolve().parent == parent.resolve()):
            shutil.rmtree(root)
        raise
