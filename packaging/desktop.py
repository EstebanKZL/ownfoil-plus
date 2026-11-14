"""Ownfoil-Plus as a desktop program: the entry point of the Windows, macOS and Linux
builds (packaging/ownfoil.spec, PyInstaller).

Double-click it, or run it from a terminal: the server starts on port 8465 and the Web UI
opens in the browser. Its settings and library data live in `config/` and `data/` next
to the program, so updating is unpacking a newer version over the same folder. A folder
given as the first argument is used instead (`Ownfoil-Plus /path/to/data`), and
`--no-browser` keeps the browser closed.

It serves with the cross-platform server (app/local.py) on every system, never gunicorn:
gunicorn needs Unix's fork and loads the app by its module path, neither of which a
frozen program has.
"""
import argparse
import multiprocessing
import os
import sys


def _program_dir():
    """The folder the program sits in (the repository, when run from source)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    # The worker processes are started anew from this program (spawn): without this, each
    # one would start a whole new server instead of running its tasks.
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(prog='Ownfoil-Plus',
                                     description='Run the Ownfoil-Plus server on this computer.')
    parser.add_argument('base_dir', nargs='?', default=None,
                        help='Folder for config/ and data/ (default: next to the program).')
    parser.add_argument('--no-browser', action='store_true',
                        help='Do not open the Web UI in the browser on start.')
    args = parser.parse_args()

    base_dir = os.path.abspath(args.base_dir or _program_dir())
    os.makedirs(base_dir, exist_ok=True)
    os.environ.setdefault('OWNFOIL_CONFIG_DIR', os.path.join(base_dir, 'config'))
    os.environ.setdefault('OWNFOIL_DATA_DIR', os.path.join(base_dir, 'data'))

    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, os.path.join(_program_dir(), 'app'))
    from local import main as run_app
    open_browser = not args.no_browser and os.environ.get('OWNFOIL_NO_BROWSER', '').strip().lower() not in ('1', 'true', 'yes')
    run_app(open_browser=open_browser)


if __name__ == '__main__':
    main()
