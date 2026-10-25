"""Control NCA metadata — currently just the human display version.

A Control NCA's RomFS carries `control.nacp`, whose DisplayVersion field is the version
string a game shows about itself (e.g. "1.2.0"), distinct from the raw Nintendo version
counter (`Apps.app_version` / `AppVersion.version`), which is a multiple of 65536 (so
"1.0.0" reads as raw 0, and a perfectly normal first release looked like "v0" on
/admin/files before this existed).

Ported from upstream ownfoil 2.5.0's `containers/nacp.py`, trimmed to the one field this
fork surfaces here. Upstream's version of this module also reads per-language name,
publisher and icon out of the same NACP/RomFS - this fork gets a title's name and icon
from titledb instead (see `titles.py`/`media.py`) and has no use for the container's own
copy of them, so that part of upstream's module is not ported.
"""
import struct

_CONTROL_NACP = 'control.nacp'
_DISPLAY_VERSION = (0x3060, 0x10)

_ROMFS_HEADER = struct.Struct('<10Q')
_ROMFS_FILE_ENTRY = struct.Struct('<IIQQII')


def _string(blob, offset, size):
    return blob[offset:offset + size].split(b'\0', 1)[0].decode('utf-8', 'replace') or None


def nacp_display_version(blob):
    """The version string a game shows about itself, e.g. '1.0.1', from a raw
    control.nacp blob. None when the field is empty (some very old titles ship no
    display version at all)."""
    return _string(blob, *_DISPLAY_VERSION)


def read_romfs_files(rom):
    """{name: (offset, size)} of the files in a RomFS section, offsets absolute within it.

    A control RomFS is flat - control.nacp and the per-language icons sit at the root - so
    the file meta table is walked straight through and the directory tables are never
    needed.
    """
    section = rom.ivfc.levels[-1].offset
    rom.seek(section)
    header = _ROMFS_HEADER.unpack(rom.read(_ROMFS_HEADER.size))
    meta_offset, meta_size, data_offset = header[7], header[8], header[9]

    rom.seek(section + meta_offset)
    meta = rom.read(meta_size)

    files = {}
    offset = 0
    while offset + _ROMFS_FILE_ENTRY.size <= len(meta):
        *_, file_offset, size, _hash, name_len = _ROMFS_FILE_ENTRY.unpack_from(meta, offset)
        name_at = offset + _ROMFS_FILE_ENTRY.size
        name = meta[name_at:name_at + name_len].decode('utf-8', 'replace')
        files[name] = (section + data_offset + file_offset, size)
        offset = name_at + ((name_len + 3) & ~3)
    return files


def read_display_version(rom):
    """The display version string out of one Control NCA's RomFS section, or None if the
    section carries no control.nacp at all (shouldn't happen for a real Control NCA, but a
    corrupt/truncated one is treated the same as "nothing to report" here rather than
    raised - the caller already has a valid identification from the CNMT and should not
    lose it over this)."""
    files = read_romfs_files(rom)
    if _CONTROL_NACP not in files:
        return None
    offset, size = files[_CONTROL_NACP]
    rom.seek(offset)
    return nacp_display_version(rom.read(size))
