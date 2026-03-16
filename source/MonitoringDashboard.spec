# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

project_root = Path(SPECPATH).resolve()
metadata_package_names = {
    'bs4': 'beautifulsoup4',
    'PIL': 'Pillow',
    'pydantic_settings': 'pydantic-settings',
    'python_multipart': 'python-multipart',
    'webview': 'pywebview',
}


def collect_optional_metadata(package_name):
    dist_name = metadata_package_names.get(package_name, package_name)
    try:
        return copy_metadata(dist_name)
    except Exception:
        return []


def collect_local_modules(root: Path, package_name: str) -> list[str]:
    package_dir = root / package_name
    if not package_dir.exists():
        return []

    modules: set[str] = set()
    for py_file in package_dir.rglob('*.py'):
        if '.' in py_file.stem:
            continue
        rel = py_file.relative_to(root).with_suffix('')
        parts = rel.parts
        if parts[-1] == '__init__':
            module_name = '.'.join(parts[:-1])
        else:
            module_name = '.'.join(parts)
        if module_name:
            modules.add(module_name)
    return sorted(modules)

datas = [
    ('presentation/templates/dashboard.html', 'presentation/templates'),
    ('presentation/templates/selector_helper.html', 'presentation/templates'),
    ('presentation/static/manifest.json', 'presentation/static'),
    ('presentation/static/preview_download_guard.js', 'presentation/static'),
    ('presentation/static/selector_helper_inject.js', 'presentation/static'),
    ('presentation/static/sw.js', 'presentation/static'),
    ('TARGET.json', '.'),
    ('config/sites.json', 'config'),
]
binaries = []
hiddenimports = [
    'pystray',
    'pystray._win32',
    'webview.platforms.edgechromium',
    'webview_app',
    'main',
    'config',
    'email.mime.text',
    'email.mime.multipart',
    'email.mime.base',
    'email.mime.message',
]

for package_name in ['application', 'config', 'domain', 'infrastructure', 'presentation']:
    hiddenimports += collect_local_modules(project_root, package_name)

pyarmor_runtime_dir = project_root / 'pyarmor_runtime_000000'
if pyarmor_runtime_dir.exists():
    datas.append((str(pyarmor_runtime_dir), 'pyarmor_runtime_000000'))
    hiddenimports.append('pyarmor_runtime_000000')

for package_name in [
    'uvicorn',
    'fastapi',
    'starlette',
    'sqlalchemy',
    'httpx',
    'bs4',
    'lxml',
    'apscheduler',
    'pydantic',
    'pydantic_settings',
    'jinja2',
    'python_multipart',
    'aiosmtplib',
    'winotify',
    'pystray',
    'PIL',
    'webview',
]:
    datas += collect_data_files(package_name)
    datas += collect_optional_metadata(package_name)
    binaries += collect_dynamic_libs(package_name)
    hiddenimports += collect_submodules(package_name)


a = Analysis(
    ['webview_app.py'],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MonitoringDashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MonitoringDashboard',
)
