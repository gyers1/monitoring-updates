"""Windows toast support helpers for classic desktop apps."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from uuid import UUID

from ctypes import wintypes


if sys.platform == "win32":
    ole32 = ctypes.OleDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
else:  # pragma: no cover - Windows only
    ole32 = None
    shell32 = None


CLSCTX_INPROC_SERVER = 0x1
COINIT_APARTMENTTHREADED = 0x2
HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid(cls, value: UUID) -> "GUID":
        data = value.bytes_le
        return cls(
            int.from_bytes(data[0:4], "little"),
            int.from_bytes(data[4:6], "little"),
            int.from_bytes(data[6:8], "little"),
            (ctypes.c_ubyte * 8).from_buffer_copy(data[8:16]),
        )


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", GUID),
        ("pid", wintypes.DWORD),
    ]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("pszVal", wintypes.LPWSTR),
    ]


IID_ISHELL_LINK_W = GUID.from_uuid(UUID("{000214F9-0000-0000-C000-000000000046}"))
IID_IPERSIST_FILE = GUID.from_uuid(UUID("{0000010B-0000-0000-C000-000000000046}"))
IID_IPROPERTY_STORE = GUID.from_uuid(UUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"))
CLSID_SHELL_LINK = GUID.from_uuid(UUID("{00021401-0000-0000-C000-000000000046}"))
PKEY_APP_USER_MODEL_ID = PROPERTYKEY(
    GUID.from_uuid(UUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")),
    5,
)


def _raise_for_hresult(result: int, action: str) -> None:
    if result < 0:
        raise OSError(f"{action} failed with HRESULT 0x{result & 0xFFFFFFFF:08X}")


def _call_vtable(obj: ctypes.c_void_p, index: int, prototype, *args):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    func = prototype(vtable[index])
    return func(obj, *args)


def _query_interface(obj: ctypes.c_void_p, iid: GUID) -> ctypes.c_void_p:
    out = ctypes.c_void_p()
    prototype = ctypes.WINFUNCTYPE(
        HRESULT,
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    )
    result = _call_vtable(obj, 0, prototype, ctypes.byref(iid), ctypes.byref(out))
    _raise_for_hresult(result, "QueryInterface")
    return out


def _release(obj: ctypes.c_void_p | None) -> None:
    if not obj:
        return
    prototype = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    _call_vtable(obj, 2, prototype)


def _shortcut_path(app_id: str) -> Path:
    programs_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return programs_dir / f"{app_id}.lnk"


def _launch_target() -> tuple[Path, str, Path, Path]:
    if getattr(sys, "frozen", False):
        target = Path(sys.executable).resolve()
        return target, "", target.parent, target

    source_dir = Path(__file__).resolve().parent.parent
    script_path = source_dir / "webview_app.py"
    pythonw_path = Path(sys.executable).with_name("pythonw.exe")
    target = pythonw_path if pythonw_path.exists() else Path(sys.executable)
    icon_path = target if target.exists() else Path(sys.executable)
    return target.resolve(), f'"{script_path}"', source_dir, icon_path.resolve()


def set_current_process_app_id(app_id: str) -> None:
    if sys.platform != "win32" or shell32 is None:  # pragma: no cover - Windows only
        return
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = HRESULT
    result = shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    _raise_for_hresult(result, "SetCurrentProcessExplicitAppUserModelID")


def ensure_start_menu_shortcut(app_id: str) -> Path:
    if sys.platform != "win32" or ole32 is None:  # pragma: no cover - Windows only
        raise OSError("Windows toast shortcuts are only available on Windows.")

    target_path, arguments, working_dir, icon_path = _launch_target()
    shortcut_path = _shortcut_path(app_id)
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = HRESULT

    shell_link = ctypes.c_void_p()
    property_store = None
    persist_file = None
    initialized = False

    try:
        result = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        if result not in (0, 1):
            _raise_for_hresult(result, "CoInitializeEx")
        initialized = True

        result = ole32.CoCreateInstance(
            ctypes.byref(CLSID_SHELL_LINK),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_ISHELL_LINK_W),
            ctypes.byref(shell_link),
        )
        _raise_for_hresult(result, "CoCreateInstance")

        set_text = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.LPCWSTR)
        set_icon = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int)

        _raise_for_hresult(_call_vtable(shell_link, 20, set_text, str(target_path)), "IShellLink.SetPath")
        _raise_for_hresult(_call_vtable(shell_link, 11, set_text, arguments), "IShellLink.SetArguments")
        _raise_for_hresult(_call_vtable(shell_link, 9, set_text, str(working_dir)), "IShellLink.SetWorkingDirectory")
        _raise_for_hresult(_call_vtable(shell_link, 7, set_text, app_id), "IShellLink.SetDescription")
        _raise_for_hresult(_call_vtable(shell_link, 17, set_icon, str(icon_path), 0), "IShellLink.SetIconLocation")

        property_store = _query_interface(shell_link, IID_IPROPERTY_STORE)
        prop_variant = PROPVARIANT()
        prop_variant.vt = 31  # VT_LPWSTR
        prop_variant.pszVal = ctypes.c_wchar_p(app_id)
        set_value = ctypes.WINFUNCTYPE(
            HRESULT,
            ctypes.c_void_p,
            ctypes.POINTER(PROPERTYKEY),
            ctypes.POINTER(PROPVARIANT),
        )
        commit = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p)
        _raise_for_hresult(
            _call_vtable(property_store, 6, set_value, ctypes.byref(PKEY_APP_USER_MODEL_ID), ctypes.byref(prop_variant)),
            "IPropertyStore.SetValue",
        )
        _raise_for_hresult(_call_vtable(property_store, 7, commit), "IPropertyStore.Commit")

        persist_file = _query_interface(shell_link, IID_IPERSIST_FILE)
        save = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.BOOL)
        _raise_for_hresult(_call_vtable(persist_file, 6, save, str(shortcut_path), True), "IPersistFile.Save")
        return shortcut_path
    finally:
        _release(persist_file)
        _release(property_store)
        _release(shell_link)
        if initialized:
            ole32.CoUninitialize()
