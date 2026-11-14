"""nsz container access — the one place that turns a path into an open Nsp/Xci."""
import logging
from contextlib import contextmanager
from pathlib import Path

from nsz.Fs import (Nca as _Nca, Nsp as _Nsp, Xci as _Xci, Pfs0 as _Pfs0, Type as _Type,
                    factory as _factory)
from nsz.nut import Print as _nsz_print

from .nacp import read_display_version, read_romfs_files

logger = logging.getLogger('main')

_nsz_print.enableInfo = False
_nsz_print.minimalOutput = True
_Pfs0.Print.silent = True


@contextmanager
def open_container(filepath, meta_only=False):
    """Open an NSP/NSZ/XCI/XCZ for reading, closed however the caller leaves."""
    path = Path(filepath)
    container = _factory(path.with_suffix(path.suffix.lower()))
    if type(container) not in (_Nsp.Nsp, _Xci.Xci):
        raise ValueError(f'Unsupported container extension: {path.suffix}')
    try:
        container.open(str(filepath), 'rb', meta_only=meta_only)
        yield container
    finally:
        container.flush()
        container.close()


def _nca_holder(container):
    """The PFS0/HFS0 an opened container keeps its NCAs in."""
    return container.hfs0['secure'] if isinstance(container, _Xci.Xci) else container


# PFS0 and HFS0 lay out a partition table the same way - magic, file count, string table
# size, padding, entries, string table - and differ only in how wide one entry is.
_ENTRY_SIZE = {b'PFS0': 0x18, b'HFS0': 0x40}


def _partition_entries(holder):
    """{name: (offset, size)} read straight off a PFS0/HFS0 partition table.

    `Pfs0.open` finishes by opening every partition it created, and `meta_only` is what
    decides which ones it creates - so re-reading the table is how to reach a file it
    skipped (a Control NCA) without paying for the ones it skipped on purpose (the much
    larger Program NCAs).
    """
    holder.seek(0)
    entry_size = _ENTRY_SIZE[holder.read(4)]
    count = holder.readInt32()
    string_table_size = holder.readInt32()
    holder.readInt32()  # padding
    header_size = 0x10 + count * entry_size + string_table_size

    holder.seek(0x10 + count * entry_size)
    string_table = holder.read(string_table_size)

    entries = {}
    for i in range(count):
        holder.seek(0x10 + i * entry_size)
        offset, size, name_offset = holder.readInt64(), holder.readInt64(), holder.readInt32()
        name = string_table[name_offset:].split(b'\0', 1)[0].decode('utf-8', 'replace')
        entries[name] = (header_size + offset, size)
    return entries


def _open_nca(holder, nca_id):
    """Open one NCA by id, whether or not the container's own open created it.

    Entries are named `<ncaId>.nca` and only a meta NCA is `<ncaId>.cnmt.nca`, so the id
    prefixes exactly one name. Returns None if the container does not carry it.
    """
    entries = _partition_entries(holder)
    name = next((n for n in entries if n.startswith(nca_id)), None)
    if name is None:
        return None
    offset, size = entries[name]
    nca = _Nca.Nca()
    holder.partition(offset, size, nca, autoOpen=False)
    nca.open(None, 'rb')
    return nca


def _romfs_of(nca):
    return next((fs for fs in nca if fs.fsType == _Type.Fs.ROMFS), None)


# A CNMT content entry is typed by its own enum, not the NCA header's `Type.Content` enum:
# the two are shifted by one (Meta=0, Program=1, Data=2, Control=3), so
# `Type.Content.CONTROL` would actually match a Data entry here - hence the literal.
_CNMT_CONTROL = 3


def read_display_versions(filepath):
    """{(app_id, version): display_version} for every content in `filepath` that ships a
    Control NCA - a DLC ships none and is simply absent from the result, same as a content
    this fork could not read for any other reason.

    Keyed the same way `titles.identify_file`'s own CNMT walk identifies a content (its own
    declared title id and version, which for an UPDATE is the update's own app id, not the
    base title's), so a caller can attach the result straight onto what it already
    identified without re-deriving anything. One extra `meta_only` open of its own, on top
    of identification's - cheap, since only the Control NCAs (a few KB each) get opened
    here, never the much larger Program NCAs.
    """
    versions = {}
    with open_container(filepath, meta_only=True) as container:
        holder = _nca_holder(container)
        for nca in holder:
            if not isinstance(nca, _Nca.Nca) or nca.header.contentType != _Type.Content.META:
                continue
            for section in nca:
                if not isinstance(section, _Pfs0.Pfs0):
                    continue
                cnmt = section.getCnmt()
                for entry in cnmt.contentEntries:
                    if entry.type != _CNMT_CONTROL:
                        continue
                    try:
                        control_nca = _open_nca(holder, entry.ncaId)
                        rom = _romfs_of(control_nca) if control_nca is not None else None
                        if rom is None:
                            logger.warning(f'Skipping unusable Control NCA {entry.ncaId}.')
                            continue
                        versions[(cnmt.titleId.upper(), cnmt.version)] = read_display_version(rom)
                    except Exception as e:
                        logger.warning(f'Could not read Control NCA {entry.ncaId}: {e}')
    return versions


# The icons a Control NCA carries, one JPEG per language; the first of these found is
# taken, else any. A DLC carries none: the game's comes first, then its update's.
ICON_PREFERENCE = ('AmericanEnglish', 'BritishEnglish', 'LatinAmericanSpanish', 'Spanish',
                   'French', 'CanadianFrench', 'German', 'Italian', 'Portuguese',
                   'BrazilianPortuguese', 'Dutch', 'Russian', 'Japanese', 'Korean',
                   'TraditionalChinese', 'SimplifiedChinese')
_ICON_PREFERENCE = [f'icon_{lang}.dat'.lower() for lang in ICON_PREFERENCE]


def pick_icon(icons):
    """The preferred one of {name or language: JPEG bytes}, or None."""
    if not icons:
        return None
    by_key = {k.lower(): v for k, v in icons.items() if v}
    for key in _ICON_PREFERENCE:
        if key in by_key:
            return by_key[key]
        bare = key[len('icon_'):-len('.dat')]
        if bare in by_key:
            return by_key[bare]
    return next(iter(by_key.values()), None)


def _romfs_icons(rom):
    files = read_romfs_files(rom)
    icons = {}
    for name, (offset, size) in files.items():
        if name.lower().startswith('icon_') and name.lower().endswith('.dat') and 0 < size <= (1 << 20):
            rom.seek(offset)
            icons[name] = rom.read(size)
    return icons


def read_icon(filepath):
    """The official icon (a JPEG) a game file carries in its Control NCA: the game's,
    else its update's. None when there is none (a DLC, a file with no control data).
    Needs the console keys, as reading the contents does."""
    found = {}
    with open_container(filepath, meta_only=True) as container:
        holder = _nca_holder(container)
        for nca in holder:
            if not isinstance(nca, _Nca.Nca) or nca.header.contentType != _Type.Content.META:
                continue
            for section in nca:
                if not isinstance(section, _Pfs0.Pfs0):
                    continue
                cnmt = section.getCnmt()
                for entry in cnmt.contentEntries:
                    if entry.type != _CNMT_CONTROL:
                        continue
                    try:
                        control_nca = _open_nca(holder, entry.ncaId)
                        rom = _romfs_of(control_nca) if control_nca is not None else None
                        icon = pick_icon(_romfs_icons(rom)) if rom is not None else None
                    except Exception as e:
                        logger.warning(f'Could not read the icon of Control NCA {entry.ncaId}: {e}')
                        icon = None
                    if icon:
                        # The game's own Control NCA wins over an update's.
                        rank = 0 if cnmt.titleId.upper().endswith('000') else 1
                        found.setdefault(rank, icon)
    return found.get(0) or found.get(1)
