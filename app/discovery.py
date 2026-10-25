"""LAN discovery: answers the UDP broadcast clients (Sphaira) send to find shops on the
local network, so the console doesn't need the server's address typed in by hand.
"""
import json
import logging
import socket
import threading
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from constants import DISCOVERY_MAGIC, DISCOVERY_PORT, DISCOVERY_REQUEST, HTTP_PORT
from settings import get_server_uid, get_settings

logger = logging.getLogger('main')

_responder = None
_lock = threading.Lock()


def _app_version():
    try:
        return _pkg_version('ownfoil')
    except PackageNotFoundError:
        return 'unknown'


def discovery_payload():
    """The reply describing this shop: who it is, and where a console can reach it."""
    shop = get_settings()['shop']
    return {
        'magic': DISCOVERY_MAGIC,
        'uid': get_server_uid(),
        'name': shop.get('name') or 'Ownfoil-Plus',
        'version': _app_version(),
        # A port, not an address: the client knows the host the reply came from.
        'port': HTTP_PORT,
        'remote': shop.get('host', ''),
        'public': shop.get('public', False),
    }


class DiscoveryResponder(threading.Thread):
    """Daemon thread answering discovery requests until stopped."""

    def __init__(self, port=DISCOVERY_PORT):
        super().__init__(daemon=True)
        self.port = port
        self.sock = None
        self._stopping = False

    def bind(self):
        """Take the UDP port, returning whether the service can run at all."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('', self.port))
        except OSError as e:
            sock.close()
            logger.warning(f'LAN discovery disabled: cannot listen on UDP port {self.port} ({e}).')
            return False
        self.sock = sock
        self.port = sock.getsockname()[1]
        return True

    def run(self):
        while not self._stopping:
            try:
                request, sender = self.sock.recvfrom(1024)
            except OSError:
                break  # stop() closed the socket under us
            if request.strip() != DISCOVERY_REQUEST:
                continue
            try:
                self.sock.sendto(json.dumps(discovery_payload()).encode(), sender)
            except OSError as e:
                logger.warning(f'Could not answer discovery request from {sender[0]}: {e}')

    def stop(self):
        """Close the socket so the blocked recvfrom returns and the thread ends."""
        self._stopping = True
        self.sock.close()
        self.join(timeout=5)


def reconcile():
    """Start or stop the responder to match the configured services."""
    global _responder
    with _lock:
        enabled = get_settings().get('services', {}).get('discovery', {}).get('enabled', False)
        if enabled:
            if _responder is None:
                responder = DiscoveryResponder(DISCOVERY_PORT)
                if responder.bind():
                    responder.start()
                    _responder = responder
                    logger.info(f'LAN discovery listening on UDP port {responder.port}.')
        elif _responder is not None:
            _responder.stop()
            _responder = None
            logger.info('LAN discovery stopped.')


def stop():
    """Stop answering, whatever the settings say."""
    global _responder
    with _lock:
        if _responder is not None:
            _responder.stop()
            _responder = None
