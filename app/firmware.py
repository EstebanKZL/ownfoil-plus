"""Console firmware versions.

TitleDB's cnmts say which system version each game and update needs
(`requiredSystemVersion`), packed as `major << 26 | minor << 20 | micro << 16 | build`;
people write theirs as 23.0.1. These two turn one into the other.
"""
import re

_FIRMWARE_RE = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{1,2})$')


def format_system_version(code):
    """`805437440` -> '12.0.2'; None for no requirement (0 or missing)."""
    if not code or code <= 0:
        return None
    return f'{code >> 26}.{(code >> 20) & 0x3F}.{(code >> 16) & 0xF}'


def parse_firmware(text):
    """'15.0.1' -> its system version code; None when it isn't a firmware version."""
    match = _FIRMWARE_RE.match((text or '').strip())
    if not match:
        return None
    major, minor, micro = (int(part) for part in match.groups())
    if major > 63 or minor > 63 or micro > 15:
        return None
    return major << 26 | minor << 20 | micro << 16
