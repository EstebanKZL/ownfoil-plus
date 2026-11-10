"""NUP files (.nup): containers of decrypted Switch games, version 1 of the format
published at github.com/a55uka/nup. One file holds a game, its updates and its DLC as
plain ExeFS/RomFS trees, each file stored raw or zstd-compressed with its SHA-256.
Nothing is encrypted, so a NUP is identified and checked without the console keys.

Layout read here (all little endian):
  header (0x80): "NUP\\x01", header size u16 @4, TOC offset u64 @8, TOC size u64 @0x10,
                 TOC SHA-256 @0x18, data offset u64 @0x38, file size u64 @0x40,
                 package count u32 @0x48, flags u32 @0x4C
  TOC: "TOC\\x01", package count u32 @4, folder count u64 @8, file count u64 @0x10,
       name pool offset u64 @0x18 and size u64 @0x20; then the packages (0x40 each),
       the folders (0x18), the files (0x50), the folders' children (u32 each) and the
       name pool.
  package: title id u64 @0, root folder u32 @8, version u32 @0x14, kind u8 @0x18
           (0 game, 1 update, 2 DLC), metadata offset u64 @0x20 and size u32 @0x28
           (TLV records: type u16, 2 reserved bytes, size u32, value).
  file: name offset/length u32 @0/@4, size u64 @8, data offset u64 @0x10, stored size
        u64 @0x18, SHA-256 @0x20, codec u8 @0x40 (0 raw, 1 zstd).

Only the header, the TOC and the package metadata are read to identify a file; the
game data is read only by verify().
"""
import hashlib
import logging
import os
import re
import struct

logger = logging.getLogger('main')

EXTENSION = 'nup'

_MAGIC = b'NUP\x01'
_TOC_MAGIC = b'TOC\x01'
_HEADER_SIZE = 0x80
_TOC_HEAD = 0x30
_PACKAGE = 0x40
_DIR = 0x18
_FILE = 0x50

KIND_BASE, KIND_UPDATE, KIND_DLC = 0, 1, 2
_KIND_MAX = 4          # 3 and 4 are reserved by the format: read, then skipped

_CODEC_RAW, _CODEC_ZSTD = 0, 1

# Far above any real file, so a damaged or hostile one is refused before it is read
# whole (the largest known game has a table of contents of about 34 MB).
_MAX_TOC = 256 << 20
_MAX_PACKAGES = 4096
_MAX_META = 32 << 20
_MAX_META_TOTAL = 64 << 20
_MAX_DEPTH = 128
_NO_DIR = 0xFFFFFFFF
# Some packer builds tag a folder's child files with the high bit instead of counting
# them after the folders: both read the same.
_FILE_TAG = 0x80000000

_TLV_NPDM = 0x0001
_TLV_DISPLAY_VERSION = 0x0004
_TLV_TITLE_NAME = 0x0005
_TLV_PUBLISHER = 0x0006
_TLV_BUILD_ID = 0x0007
_TLV_SOURCE_DUMP = 0x0008
_TLV_LOCALIZED_TITLES = 0x0009
_TLV_LOCALIZED_ICONS = 0x000A

# The console takes paths of 0x300 bytes at most, so no game has longer names; a crafted
# NUP that gives longer ones is refused, and so is a path past 0x400.
_MAX_NAME = 0x300
_MAX_PATH = 0x400

_READ_CHUNK = 4 << 20

# "Game [0100...][v65536]": tags some packers leave in the stored name.
_NAME_TAGS = re.compile(r'\s*\[(?:[0-9A-Fa-f]{16}|[vV]\d+)\]')


class NupError(ValueError):
    """The file is not a NUP this reader can trust."""


def is_nup(path):
    return os.path.splitext(path)[1].lower() == '.' + EXTENSION


def _u16(b, o): return struct.unpack_from('<H', b, o)[0]
def _u32(b, o): return struct.unpack_from('<I', b, o)[0]
def _u64(b, o): return struct.unpack_from('<Q', b, o)[0]


def _read_at(f, offset, size):
    f.seek(offset)
    data = f.read(size)
    if len(data) != size:
        raise NupError('the file is cut short')
    return data


def _tlvs(block):
    """The first record of each type in a package's metadata block, and whether its types
    were counted from 0.

    A build of the format's packer numbered the types one below the format's (NPDM 0, the
    name 4, the publisher 5): a block with a type 0 is read with each type one up. A block
    without an NPDM (a DLC's) has no type 0 to tell it: there a record 0x0007 that is not
    the 32 bytes of a build ID does - the source dump's name, one below its place. The
    reference packer, NXPress and Switch Library Manager read them by the same two rules."""
    records, pos = {}, 0
    while pos + 8 <= len(block):
        kind, size = _u16(block, pos), _u32(block, pos + 4)
        pos += 8
        if size > len(block) - pos:
            raise NupError('a metadata record runs past its block')
        records.setdefault(kind, block[pos:pos + size])
        pos += size
    build_id = records.get(_TLV_BUILD_ID)
    if 0 not in records and (build_id is None or len(build_id) == 32):
        return records, False
    return {(k + 1 if k < 0xFF else k): v for k, v in records.items()}, True


def _localized(payload):
    """Names or icons by language: a tag's length, the tag, the data's length, the data.
    Raises NupError when a record runs past the block."""
    result, pos = {}, 0
    while pos < len(payload):
        tag_size = payload[pos]
        pos += 1
        if not tag_size or tag_size > len(payload) - pos - 4:
            raise NupError('a record is malformed')
        tag = payload[pos:pos + tag_size].decode('ascii', 'replace').lower()
        pos += tag_size
        size = _u32(payload, pos)
        pos += 4
        if size > len(payload) - pos:
            raise NupError('a record runs past the end of its block')
        result.setdefault(tag, payload[pos:pos + size])
        pos += size
    return result


def _utf8(raw):
    try:
        raw.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def _label(pkg):
    kind = {KIND_BASE: 'game', KIND_UPDATE: 'update'}.get(pkg['kind'])
    if kind:
        return f"{kind} v{pkg['version']}"
    if pkg['kind'] == KIND_DLC:
        return f"DLC {pkg['title_id']:016X} v{pkg['version']}"
    return f"package of kind {pkg['kind']} v{pkg['version']}"


def _damaged_meta(container):
    """The packages' metadata that cannot be what it says - no hash of the format covers
    it: a build ID that is not 32 bytes, text that is not UTF-8, names or icons by language
    that run past their record. Types are only sure in a block with an NPDM (a block
    without one could be counted from 0 unseen), so elsewhere only the by-language records,
    alike either way, are looked at."""
    damaged = []
    for pkg in container['packages']:
        meta = pkg['meta']

        def bad(record, reason):
            damaged.append(f"{_label(pkg)}: metadata, {record}: {reason}")
        names = {}
        for kind, record in ((_TLV_LOCALIZED_TITLES, 'names by languages'),
                             (_TLV_LOCALIZED_ICONS, 'icons by languages')):
            if kind in meta:
                try:
                    parsed = _localized(meta[kind])
                except NupError as e:
                    bad(record, str(e))
                    continue
                if kind == _TLV_LOCALIZED_TITLES:
                    names = parsed
        if not (meta.get(_TLV_NPDM) or b'').startswith(b'META'):
            continue
        build_id = meta.get(_TLV_BUILD_ID)
        if build_id is not None and len(build_id) != 32:
            bad('build ID', f'it is {len(build_id)} bytes instead of 32')
        for kind, record in ((_TLV_DISPLAY_VERSION, 'display version'), (_TLV_TITLE_NAME, 'name'),
                             (_TLV_PUBLISHER, 'publisher'), (_TLV_SOURCE_DUMP, 'source dump')):
            if kind in meta and not _utf8(meta[kind]):
                bad(record, 'it is not UTF-8 text')
        for tag in sorted(names):
            if not _utf8(names[tag]):
                bad('names by languages', f'the name in {tag} is not UTF-8 text')
    return damaged


def _text(raw, limit):
    text = (raw or b'').decode('utf-8', 'ignore')
    text = ''.join(ch for ch in text if ch >= ' ' and ch != '\x7f').strip()
    return text[:limit]


def read(path):
    """Header, table of contents and package metadata of a NUP, checked as the format
    asks of a reader (sizes and offsets inside the file, the TOC's hash). Returns a dict
    with `packages`, `dirs`, `files` and `children`; raises NupError otherwise."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        header = _read_at(f, 0, _HEADER_SIZE) if size >= _HEADER_SIZE else b''
        if header[:4] != _MAGIC:
            if header[:3] == b'NUP':
                raise NupError(f'NUP version {header[3]} is not supported')
            raise NupError('not a NUP file')
        header_size = _u16(header, 0x04)
        toc_offset, toc_size = _u64(header, 0x08), _u64(header, 0x10)
        toc_hash = header[0x18:0x38]
        data_offset, file_size = _u64(header, 0x38), _u64(header, 0x40)
        package_count, flags = _u32(header, 0x48), _u32(header, 0x4C)
        if header_size < _HEADER_SIZE:
            raise NupError('the NUP header is too small')
        if flags:
            raise NupError(f'NUP flags {flags:#x} are not supported')
        if not header_size <= toc_offset <= file_size:
            raise NupError('the table of contents is outside the file')
        if not _TOC_HEAD <= toc_size <= _MAX_TOC:
            raise NupError('the table of contents has an invalid size')
        if not 0 < package_count <= _MAX_PACKAGES or _TOC_HEAD + package_count * _PACKAGE > toc_size:
            raise NupError('the NUP has an invalid number of packages')
        if data_offset % 16 or data_offset < toc_offset + toc_size:
            raise NupError('the data region overlaps the table of contents')
        if size < file_size:
            raise NupError(f'the file is cut short ({size} of {file_size} bytes)')
        if size != file_size or data_offset > file_size:
            raise NupError('the file size does not match its header')

        toc = _read_at(f, toc_offset, toc_size)
        if hashlib.sha256(toc).digest() != toc_hash:
            raise NupError('the table of contents is damaged (its hash does not match)')
        if toc[:4] != _TOC_MAGIC or _u32(toc, 0x04) != package_count:
            raise NupError('the table of contents has an unknown format')
        dir_count, file_count = _u64(toc, 0x08), _u64(toc, 0x10)
        pool_offset, pool_size = _u64(toc, 0x18), _u64(toc, 0x20)
        records = _TOC_HEAD + package_count * _PACKAGE + dir_count * _DIR + file_count * _FILE
        if records > toc_size:
            raise NupError('folders and files do not fit in the table of contents')
        if not records <= pool_offset <= toc_size or pool_size > toc_size - pool_offset \
                or (pool_offset - records) % 4:
            raise NupError('the names are outside the table of contents')
        pool = toc[pool_offset:pool_offset + pool_size]

        def name(rec):
            off, length = _u32(rec, 0), _u32(rec, 4)
            if off + length > pool_size:
                raise NupError('a name is outside the table of contents')
            if length > _MAX_NAME:
                raise NupError(f'a name is too long ({length} bytes)')
            return pool[off:off + length].decode('utf-8', 'replace')

        packages, meta_total = [], 0
        for i in range(package_count):
            rec = toc[_TOC_HEAD + i * _PACKAGE:][:_PACKAGE]
            kind = rec[0x18]
            if kind > _KIND_MAX:
                raise NupError(f'package {i} has an unknown kind ({kind})')
            root, exefs, romfs = _u32(rec, 0x08), _u32(rec, 0x0C), _u32(rec, 0x10)
            if root >= dir_count or any(d != _NO_DIR and d >= dir_count for d in (exefs, romfs)):
                raise NupError(f'package {i} has its folders outside the table of contents')
            meta, zero_based = {}, False
            meta_offset, meta_size = _u64(rec, 0x20), _u32(rec, 0x28)
            if meta_size:
                meta_total += meta_size
                if meta_size > _MAX_META or meta_total > _MAX_META_TOTAL \
                        or not header_size <= meta_offset <= file_size or meta_size > file_size - meta_offset:
                    raise NupError(f'package {i} has its metadata outside the file')
                meta, zero_based = _tlvs(_read_at(f, meta_offset, meta_size))
            # zero_based: told (and read one up), never written back - the file stays as it is.
            packages.append({'title_id': _u64(rec, 0), 'root': root, 'version': _u32(rec, 0x14),
                             'kind': kind, 'flags': rec[0x19], 'meta': meta, 'zero_based': zero_based})

    pos = _TOC_HEAD + package_count * _PACKAGE
    child_count = (pool_offset - records) // 4
    dirs = []
    # Each folder has a range of children of its own, as the format lays them out: folders
    # whose ranges overlap would make every walk go through the same children again and again.
    slots = 0
    for _ in range(dir_count):
        rec = toc[pos:pos + _DIR]
        pos += _DIR
        first, count = _u32(rec, 0x08), _u32(rec, 0x0C)
        if first + count > child_count:
            raise NupError('a folder has its children outside the table of contents')
        slots += count
        if slots > child_count:
            raise NupError('folders share their children')
        dirs.append((name(rec), first, count))
    files = []
    for _ in range(file_count):
        rec = toc[pos:pos + _FILE]
        pos += _FILE
        entry = {'name': name(rec), 'size': _u64(rec, 0x08), 'offset': _u64(rec, 0x10),
                 'stored': _u64(rec, 0x18), 'sha256': bytes(rec[0x20:0x40]), 'codec': rec[0x40]}
        if entry['codec'] > _CODEC_ZSTD:
            raise NupError(f"file {entry['name']!r} uses an unknown codec ({entry['codec']})")
        if entry['size']:
            if entry['offset'] < data_offset or entry['offset'] % 16 or entry['offset'] > file_size \
                    or entry['stored'] > file_size - entry['offset']:
                raise NupError(f"file {entry['name']!r} has its data outside the file")
            if entry['codec'] == _CODEC_RAW and entry['stored'] != entry['size']:
                raise NupError(f"file {entry['name']!r} is stored raw with the wrong size")
            if entry['codec'] == _CODEC_ZSTD and not entry['stored']:
                raise NupError(f"file {entry['name']!r} has no data")
        files.append(entry)
    children = []
    for _ in range(child_count):
        node = _u32(toc, pos)
        pos += 4
        if node >= _FILE_TAG:
            node = dir_count + (node - _FILE_TAG)
        if node >= dir_count + file_count:
            raise NupError('a folder holds something that is not in the table of contents')
        children.append(node)
    container = {'packages': packages, 'dirs': dirs, 'files': files, 'children': children}
    _check_walks(container)
    return container


def _check_walks(container):
    """Refuse a tree whose walks would go through the same children again and again. As
    packers write a NUP each package has a tree of its own, so all the walks together go
    through each child once; a crafted NUP whose packages all share one big tree would
    keep a reader at it for hours. Folders are walked as walk() does, without the paths."""
    dirs, children = container['dirs'], container['children']
    budget = 4 * len(children) + 1024
    stamp = [0] * len(dirs)       # per folder: 2p+1 while package p walks it, 2p+2 once walked
    for p, pkg in enumerate(container['packages']):
        open_ = 2 * p + 1
        stack = [[pkg['root'], 0]]
        stamp[pkg['root']] = open_
        while stack:
            top = stack[-1]
            _, first, count = dirs[top[0]]
            if top[1] == count:
                stamp[top[0]] = open_ + 1
                stack.pop()
                continue
            node = children[first + top[1]]
            top[1] += 1
            budget -= 1
            if budget < 0:
                raise NupError('the packages share their folders too many times')
            # A folder inside itself, or too deep, is told by walk().
            if node >= len(dirs) or stamp[node] >= open_ or len(stack) >= _MAX_DEPTH:
                continue
            stamp[node] = open_
            stack.append([node, 0])


def walk(container, package_index):
    """(path, file index) of every file of one package, in tree order. A folder held by
    two folders is walked once; a folder inside itself, or one too deep, is an error."""
    dirs, files, children = container['dirs'], container['files'], container['children']
    root = container['packages'][package_index]['root']
    state = {root: 'open'}
    stack = [[root, 0, '']]
    while stack:
        top = stack[-1]
        dname, first, count = dirs[top[0]]
        if top[1] == count:
            state[top[0]] = 'done'
            stack.pop()
            continue
        node = children[first + top[1]]
        top[1] += 1
        if node >= len(dirs):
            index = node - len(dirs)
            path = top[2] + files[index]['name']
            if len(path.encode()) > _MAX_PATH:
                raise NupError('a path is too long')
            yield path, index
            continue
        seen = state.get(node)
        if seen == 'open':
            raise NupError(f'folder {dirs[node][0]!r} is inside itself')
        if seen == 'done':
            continue
        if len(stack) >= _MAX_DEPTH:
            raise NupError('the folders go too deep')
        prefix = top[2] + dirs[node][0] + '/'
        if len(prefix.encode()) > _MAX_PATH:
            raise NupError('a path is too long')
        state[node] = 'open'
        stack.append([node, 0, prefix])


def _stored_sizes(container):
    """Bytes of the file each package's data takes. Data shared by several packages (an
    update keeps most of its game's files unchanged) counts once: game first, then
    updates, then DLC."""
    sizes = [0] * len(container['packages'])
    claimed = set()
    for kind in range(_KIND_MAX + 1):
        for i, pkg in enumerate(container['packages']):
            if pkg['kind'] != kind:
                continue
            try:
                for _, index in walk(container, i):
                    entry = container['files'][index]
                    if entry['size'] and entry['offset'] not in claimed:
                        claimed.add(entry['offset'])
                        sizes[i] += entry['stored']
            except NupError:
                sizes[i] = 0
    return sizes


def app_id(pkg):
    """The id the library files a package under: the game's own, an update's with 800 at
    the end (the game and its updates are stored with the program id), a DLC's own."""
    tid = pkg['title_id']
    if pkg['kind'] == KIND_UPDATE and not tid & 0x800:
        tid = (tid & ~0xFFF) | 0x800
    return f'{tid:016X}'


def _program_id(packages):
    """The game's id as the other packages tell it: an update is stored with it (or with
    its own id, 800 at the end), a DLC's id is the game's + 0x1000 + its number."""
    for pkg in packages:
        if pkg['title_id'] and pkg['kind'] in (KIND_BASE, KIND_UPDATE):
            return pkg['title_id'] & ~0xFFF
    for pkg in packages:
        if pkg['title_id'] and pkg['kind'] == KIND_DLC:
            return (pkg['title_id'] & ~0xFFF) - 0x1000
    return None


def contents(path):
    """What the NUP holds, as identify_file lists the contents of an NSP or XCI: one
    entry per game / update / DLC (an update stored twice keeps its newest version),
    each with the name, display version and bytes of the file it takes."""
    container = read(path)
    shifted = [_label(p) for p in container['packages'] if p['zero_based']]
    if shifted:
        # Told, never rewritten: read one up, as the format means it.
        logger.info(f'{os.path.basename(path)}: metadata types counted from 0 in '
                    f'{", ".join(shifted)} (an early packer); read one up.')
    sizes = _stored_sizes(container)
    program = _program_id(container['packages'])
    by_app = {}
    for i, pkg in enumerate(container['packages']):
        if pkg['kind'] not in (KIND_BASE, KIND_UPDATE, KIND_DLC):
            continue        # a reserved kind
        if not pkg['title_id']:
            # A game dumped without its NPDM carries no id: it is the program the update
            # or DLC beside it belong to (seen in Switch 2 NUPs, listed as "Update + DLC").
            if pkg['kind'] != KIND_BASE or not program:
                continue
            pkg = {**pkg, 'title_id': program}
        aid = app_id(pkg)
        meta = pkg['meta']
        entry = by_app.get(aid)
        stored = sizes[i] + (entry['stored_size'] if entry else 0)
        if entry and entry['version'] >= pkg['version']:
            entry['stored_size'] = stored
            continue
        by_app[aid] = {
            'kind': pkg['kind'], 'app_id': aid, 'version': pkg['version'], 'stored_size': stored,
            'name': _NAME_TAGS.sub('', _text(meta.get(_TLV_TITLE_NAME), 0x200)).strip() or None,
            'publisher': _text(meta.get(_TLV_PUBLISHER), 0x100) or None,
            'display_version': _text(meta.get(_TLV_DISPLAY_VERSION), 0x0F) or None,
        }
    if not by_app:
        raise NupError('the NUP holds no game, update or DLC with an id')
    return list(by_app.values())


def verify(path, progress=None):
    """Check every file of the NUP against its SHA-256 (decompressing zstd data), after
    the table of contents' own hash. Returns (ok, error)."""
    import zstandard
    try:
        container = read(path)
    except (NupError, OSError) as e:
        return False, str(e)
    # The metadata no hash covers: told with the files' damage.
    failed = _damaged_meta(container)
    files = [f for f in container['files'] if f['size']]
    # Data an update shares with its game is stored once: check each extent once.
    unique = {f['offset']: f for f in files}
    total = sum(f['stored'] for f in unique.values()) or 1
    done = 0
    decompressor = zstandard.ZstdDecompressor()
    with open(path, 'rb') as fh:
        for entry in unique.values():
            digest = hashlib.sha256()
            try:
                fh.seek(entry['offset'])
                if entry['codec'] == _CODEC_ZSTD:
                    reader = decompressor.stream_reader(_Window(fh, entry['stored']))
                    produced = 0
                    while chunk := reader.read(_READ_CHUNK):
                        produced += len(chunk)
                        if produced > entry['size']:
                            raise NupError('more data than its size')
                        digest.update(chunk)
                    if produced != entry['size']:
                        raise NupError('less data than its size')
                else:
                    left = entry['stored']
                    while left:
                        chunk = fh.read(min(_READ_CHUNK, left))
                        if not chunk:
                            raise NupError('cut short')
                        digest.update(chunk)
                        left -= len(chunk)
            except (NupError, zstandard.ZstdError, OSError) as e:
                failed.append(f"{entry['name']}: {e}")
            else:
                if digest.digest() != entry['sha256']:
                    failed.append(f"{entry['name']}: SHA-256 mismatch")
            done += entry['stored']
            if progress:
                progress(done / total)
            if len(failed) >= 20:
                break
    if failed:
        return False, '; '.join(failed)[:2000]
    return True, None


class _Window:
    """A file object that reads only the next `size` bytes of another one."""

    def __init__(self, fh, size):
        self.fh, self.left = fh, size

    def read(self, n=-1):
        if self.left <= 0:
            return b''
        n = self.left if n is None or n < 0 else min(n, self.left)
        data = self.fh.read(n)
        self.left -= len(data)
        return data
