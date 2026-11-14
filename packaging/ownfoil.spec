# PyInstaller spec for the desktop builds of Ownfoil-Plus (Windows, macOS, Linux).
#
#     pyinstaller packaging/ownfoil.spec
#
# makes dist/Ownfoil-Plus/: the program (Ownfoil-Plus.exe on Windows) with everything it
# needs beside it. The app's modules are flat (`import tasks`), so each is named as a
# hidden import and analysed from app/; what Flask, Alembic and the translations read
# from disk (templates, static files, locales, migrations) is copied next to them, where
# the app looks for it (the folder its modules come from).
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
APP = os.path.join(ROOT, 'app')


def app_modules():
    """Every module of app/, by the flat name the app imports it with."""
    names = []
    for folder, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'migrations', 'static', 'templates',
                                                'locales', 'data', 'config')]
        for name in files:
            if name.endswith('.py'):
                rel = os.path.relpath(os.path.join(folder, name), APP)[:-3]
                module = rel.replace(os.sep, '.')
                names.append(module[:-len('.__init__')] if module.endswith('.__init__') else module)
    return sorted(names)


datas = [
    (os.path.join(APP, 'templates'), 'templates'),
    (os.path.join(APP, 'static'), 'static'),
    (os.path.join(APP, 'locales'), 'locales'),
    (os.path.join(APP, 'migrations'), 'migrations'),
    (os.path.join(APP, 'data', 'titledb', 'languages.json'), os.path.join('data', 'titledb')),
    (os.path.join(ROOT, 'pyproject.toml'), '.'),
    (os.path.join(ROOT, 'LICENSE.md'), '.'),
    (os.path.join(ROOT, 'NOTICE.md'), '.'),
]
datas += collect_data_files('strawberry')
datas += collect_data_files('alembic')

hiddenimports = app_modules()
hiddenimports += collect_submodules('nsz') + collect_submodules('nstools')
hiddenimports += collect_submodules('strawberry') + collect_submodules('alembic')
hiddenimports += ['sqlalchemy.dialects.sqlite', 'logging.config']

a = Analysis(
    [os.path.join(SPECPATH, 'desktop.py')],
    pathex=[APP],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['gunicorn', 'tkinter', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Ownfoil-Plus',
    # The program's own icon (Windows; macOS and Linux show their default).
    icon=os.path.join(APP, 'static', 'favicon', 'favicon.ico'),
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Ownfoil-Plus')
