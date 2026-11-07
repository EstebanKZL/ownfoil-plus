"""Combine a game's loose files - base, latest update, DLC - into one NSP (or NSZ).

An NSP/NSZ is a PFS0: a small header (file count, entries, names) followed by each file's
bytes. Combining copies every NCA/NCZ, ticket and certificate of the parts into one new
PFS0, byte for byte, without decrypting or recompressing anything:

- the update's delta fragments are left out (installers never need them);
- a file present in two parts (a shared certificate) is written once;
- the loose parts' metadata XML is left out (the CNMT NCAs carry the same).

The result is checked before it counts: every NCA of every part must be in it with the
same content hash. Nothing here deletes anything - the caller does that once it's sure.
"""
import logging
import os
import shutil
import struct
from pathlib import Path

logger = logging.getLogger('main')

_KEEP = ('.nca', '.ncz', '.tik', '.cert')
# CNMT content type of a delta fragment (an update's patch-of-a-patch).
_DELTA_FRAGMENT = 6
_COPY_CHUNK = 8 * 1024 * 1024


def read_pfs0(path):
    """The entries of a PFS0 file: [(name, absolute offset, size)]."""
    with open(path, 'rb') as f:
        head = f.read(16)
        if len(head) < 16 or head[:4] != b'PFS0':
            raise ValueError(f'{os.path.basename(path)} is not an NSP/NSZ (no PFS0 header).')
        count, strtab_size = struct.unpack('<II', head[4:12])
        if count > 100000:
            raise ValueError(f'{os.path.basename(path)} has an implausible file count.')
        raw = f.read(24 * count)
        strtab = f.read(strtab_size)
        if len(raw) < 24 * count or len(strtab) < strtab_size:
            raise ValueError(f'{os.path.basename(path)} is cut short.')
    data_start = 16 + 24 * count + strtab_size
    total = os.path.getsize(path)
    entries = []
    for i in range(count):
        offset, size, name_offset, _ = struct.unpack('<QQII', raw[24 * i:24 * (i + 1)])
        end = strtab.find(b'\0', name_offset)
        name = strtab[name_offset:end if end >= 0 else None].decode('utf-8', 'replace')
        start = data_start + offset
        if start + size > total:
            raise ValueError(f'{os.path.basename(path)}: {name} runs past the end of the file.')
        entries.append((name, start, size))
    return entries


def delta_nca_ids(path):
    """The NCA ids an update lists as delta fragments (needs the console keys). An
    unreadable CNMT gives none: the fragments are then kept, which installers ignore."""
    try:
        from nsz.Fs import Pfs0
        from .container import open_container
        ids = set()
        with open_container(path, meta_only=True) as container:
            for section in container.cnmt():
                if isinstance(section, Pfs0.Pfs0):
                    for entry in section.getCnmt().contentEntries:
                        if entry.type == _DELTA_FRAGMENT:
                            ids.add(str(entry.ncaId).lower())
        return ids
    except Exception as e:
        logger.warning(f'Could not read the delta fragments of {os.path.basename(path)}: {e}')
        return set()


def plan(parts, drop_ids=()):
    """Which files of which parts go into the combined file: [(name, path, offset, size)]."""
    drop = {i.lower() for i in drop_ids}
    chosen, seen = [], set()
    for path in parts:
        for name, offset, size in read_pfs0(path):
            lower = name.lower()
            if not lower.endswith(_KEEP) or lower in seen:
                continue
            if lower.split('.')[0] in drop:
                continue
            seen.add(lower)
            chosen.append((name, str(path), offset, size))
    return chosen


def write_pfs0(out_path, files, progress=None):
    """Write a PFS0 holding `files` ([(name, source path, offset, size)])."""
    names = b''
    name_offsets = []
    for name, *_ in files:
        name_offsets.append(len(names))
        names += name.encode('utf-8') + b'\0'
    header_len = 16 + 24 * len(files) + len(names)
    names += b'\0' * ((-header_len) % 0x20)        # header padded to 0x20, as nsz writes it
    entries, offset = b'', 0
    for (name, _, _, size), name_offset in zip(files, name_offsets):
        entries += struct.pack('<QQII', offset, size, name_offset, 0)
        offset += size
    total = offset or 1
    done = 0
    with open(out_path, 'wb') as out:
        out.write(b'PFS0' + struct.pack('<II', len(files), len(names)) + b'\0' * 4)
        out.write(entries)
        out.write(names)
        for _, path, start, size in files:
            with open(path, 'rb') as src:
                src.seek(start)
                left = size
                while left:
                    chunk = src.read(min(_COPY_CHUNK, left))
                    if not chunk:
                        raise IOError(f'{os.path.basename(path)} ended early.')
                    out.write(chunk)
                    left -= len(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done / total)


def output_extension(parts):
    """NSZ if any part is compressed (its NCZs go in as they are), NSP otherwise."""
    return 'nsz' if any(str(p).lower().endswith('.nsz') for p in parts) else 'nsp'


def combine(parts, out_path, updates=(), progress=None, verify=True):
    """Combine `parts` (base first) into `out_path`, check it, return the written path.
    `updates` are the parts whose delta fragments are left out."""
    if verify:
        from settings import ensure_keys
        ensure_keys('combine')     # reading the NCAs to check them needs the console keys
    for p in parts:
        if not str(p).lower().endswith(('.nsp', '.nsz')):
            raise ValueError(f'{os.path.basename(str(p))}: only NSP and NSZ files can be combined.')
    drop = set()
    for u in updates:
        drop |= delta_nca_ids(u)
    files = plan(parts, drop)
    if not any(n.lower().endswith(('.nca', '.ncz')) for n, *_ in files):
        raise ValueError('Nothing to combine: the parts hold no NCA.')
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(out_path))).free
    need = sum(size for *_, size in files)
    if free < need + 64 * 1024 * 1024:
        raise OSError(f'Not enough free space to combine ({need} bytes needed).')
    # Written at its final name (nsz reads a container by its extension); the caller marks
    # the path as in progress so scans and the watcher leave it alone until it's checked.
    if os.path.exists(out_path):
        raise FileExistsError(f'{os.path.basename(str(out_path))} already exists.')
    try:
        write_pfs0(out_path, files, (lambda f: progress(f * (0.5 if verify else 1.0))) if progress else None)
        if verify:
            check(parts, out_path, drop, (lambda f: progress(0.5 + f / 2)) if progress else None)
    except BaseException:
        Path(out_path).unlink(missing_ok=True)   # never leave an unchecked file behind
        raise
    return str(out_path)


def check(parts, out_path, drop=(), progress=None):
    """Every NCA of every part (but the dropped delta fragments) must be in the combined
    file with the same content hash. Raises ValueError otherwise."""
    from .compression import _nca_content_hashes
    expected = {}
    for p in parts:
        for key, value in _nca_content_hashes(p).items():
            if key.lower() not in drop:
                expected[key] = value
    if progress:
        progress(0.5)
    got = _nca_content_hashes(out_path)
    bad = sorted(k for k, v in expected.items() if got.get(k) != v)
    if bad:
        raise ValueError(f'The combined file does not match its parts ({len(bad)} NCA(s) differ or are missing).')
    if progress:
        progress(1.0)


# --- Splitting a combined file back into its parts -----------------------------------

def read_contents(path):
    """What a combined NSP/NSZ holds, from its CNMTs (needs the console keys):
    [{'title_id', 'version', 'type', 'cnmt': name, 'ncas': {nca ids}}]."""
    from nsz.Fs import Nca, Pfs0, Type
    from .container import open_container
    out = []
    with open_container(path, meta_only=True) as container:
        for f in container:
            if not isinstance(f, Nca.Nca) or f.header.contentType != Type.Content.META:
                continue
            for section in f:
                if isinstance(section, Pfs0.Pfs0):
                    cnmt = section.getCnmt()
                    out.append({'title_id': cnmt.titleId.upper(), 'version': int(cnmt.version),
                                'type': cnmt.titleType,
                                'cnmt': os.path.basename(f._path),
                                'ncas': {str(e.ncaId).lower() for e in cnmt.contentEntries}})
    return out


def split_plan(path, contents):
    """Each part's files: [(content, [(name, path, offset, size)])]. A ticket or
    certificate goes with the content whose title id begins its name (its rights id)."""
    entries = read_pfs0(path)
    parts = []
    for content in contents:
        tid = content['title_id'].lower()
        files = []
        for name, offset, size in entries:
            lower = name.lower()
            stem = lower.split('.')[0]
            if lower == content['cnmt'].lower():
                files.append((name, str(path), offset, size))
            elif lower.endswith(('.nca', '.ncz')) and stem in content['ncas']:
                files.append((name, str(path), offset, size))
            elif lower.endswith(('.tik', '.cert')) and stem.startswith(tid):
                files.append((name, str(path), offset, size))
        parts.append((content, files))
    return parts


def split(path, outputs, contents=None, verify=True, progress=None):
    """Split a combined file into one file per content. `outputs` maps a content's
    (title id, version) to its output path. Every written file is checked against the
    combined one (content hashes) before this returns; on any failure all are removed."""
    if verify:
        from settings import ensure_keys
        ensure_keys('split')
    contents = contents if contents is not None else read_contents(path)
    if len(contents) < 2:
        raise ValueError(f'{os.path.basename(str(path))} holds a single content: nothing to split.')
    plan = split_plan(path, contents)
    written = []
    try:
        for i, (content, files) in enumerate(plan):
            out = outputs[(content['title_id'], content['version'])]
            if os.path.exists(out):
                raise FileExistsError(f'{os.path.basename(out)} already exists.')
            if not any(n.lower().endswith(('.nca', '.ncz')) for n, *_ in files):
                raise ValueError(f'No NCA found for {content["title_id"]}.')
            written.append(out)          # removed on failure, even half written
            write_pfs0(out, files, (lambda f, i=i: progress((i + f) / len(plan) * (0.5 if verify else 1)))
                       if progress else None)
        if verify:
            from .compression import _nca_content_hashes
            source = _nca_content_hashes(path)
            for out in written:
                for key, value in _nca_content_hashes(out).items():
                    if source.get(key) != value:
                        raise ValueError(f'{os.path.basename(out)} does not match the combined file.')
            if progress:
                progress(1.0)
    except BaseException:
        for out in written:
            Path(out).unlink(missing_ok=True)
        raise
    return written
