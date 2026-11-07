"""CNMT metadata extraction — the title id, type and version a container declares."""
import logging
import re

from nsz.Fs import Nca, Nsp, Pfs0, Type, Xci

from constants import APP_TYPE_MAP

from .container import open_container

logger = logging.getLogger('main')


def get_cnmts(container):
    cnmts = []
    if isinstance(container, Nsp.Nsp):
        # Every CNMT, not only the first: an NSP that bundles a game with its update and
        # DLC (Files > Combine makes them) holds one per content. nsz's Nsp.cnmt() stops
        # at the first one, which read such a bundle as its base game alone.
        cnmts = [f for f in container
                 if isinstance(f, Nca.Nca) and f._path.lower().endswith('.cnmt.nca')]
        if not cnmts:
            try:
                cnmts.append(container.cnmt())
            except Exception as e:
                logger.warning(f'CNMT section not found in Nsp: {e}')
                raise

    elif isinstance(container, Xci.Xci):
        container = container.hfs0['secure']
        for nspf in container:
            if isinstance(nspf, Nca.Nca) and nspf.header.contentType == Type.Content.META:
                cnmts.append(nspf)
        if not cnmts:
            raise ValueError("No META NCA found in XCI secure partition.")

    else:
        raise ValueError(f"Unsupported container type: {type(container).__name__}.")

    return cnmts


# A base game's and an update's CNMT carry, in their extended header (at 0x20), the id
# they point at (8 bytes) and then the console firmware they need: RequiredSystemVersion.
# nsz's Cnmt only reads the common header, so it is read here by offset.
_EXTENDED_HEADER = 0x20
_TYPES_WITH_REQUIRED_SYSTEM_VERSION = (0x80, 0x81)   # application, patch


def required_system_version(cnmt, title_type):
    """The firmware a base game or update needs (as stored: a u32), or None."""
    if title_type not in _TYPES_WITH_REQUIRED_SYSTEM_VERSION:
        return None
    try:
        cnmt.seek(_EXTENDED_HEADER + 8)
        value = cnmt.readInt32() & 0xFFFFFFFF
    except Exception as e:
        logger.debug(f'Could not read RequiredSystemVersion: {e}')
        return None
    return value or None


def extract_meta_from_cnmt(cnmt_sections):
    """(type, title id, version, required system version or None) per CNMT."""
    contents = []
    for section in cnmt_sections:
        if isinstance(section, Pfs0.Pfs0):
            Cnmt = section.getCnmt()
            titleType = APP_TYPE_MAP[Cnmt.titleType]
            titleId = Cnmt.titleId.upper()
            version = Cnmt.version
            contents.append((titleType, titleId, version,
                             required_system_version(Cnmt, Cnmt.titleType)))
    if not contents:
        raise ValueError("No Pfs0 sections found in CNMT container.")
    return contents


def identify_file_from_cnmt(filepath):
    contents = []
    try:
        with open_container(filepath, meta_only=True) as container:
            for cnmt_sections in get_cnmts(container):
                contents += extract_meta_from_cnmt(cnmt_sections)
    except OSError as e:
        # Check if the error is due to a missing master_key
        match = re.search(r"master_key_([0-9a-fA-F]{2}) missing from", str(e))
        if match:
            key_index = match.group(1)
            raise ValueError(f"Missing valid master_key_{key_index} from keys file.") from e
        else:
            raise # Re-raise other OSErrors

    return contents
