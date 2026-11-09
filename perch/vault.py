"""API tokens kept in Windows Credential Manager (never in config.json).

Each secret is a generic credential named "Perch/<key>", visible under
Control Panel > Credential Manager > Windows Credentials.
"""

import ctypes
from ctypes import wintypes

from perch.util import IS_WIN

PREFIX = "Perch/"
_memory = {}  # fallback store for non-Windows (tests)

if IS_WIN:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    _adv.CredWriteW.restype = wintypes.BOOL
    _adv.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIAL)),
    ]
    _adv.CredReadW.restype = wintypes.BOOL
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredDeleteW.restype = wintypes.BOOL
    _adv.CredFree.argtypes = [ctypes.c_void_p]


def set_secret(key, value):
    if not IS_WIN:
        _memory[key] = value
        return
    blob = value.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = PREFIX + key
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "Perch"
    if not _adv.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), "Couldn't save the token to Windows Credential Manager")


def get_secret(key):
    if not IS_WIN:
        return _memory.get(key)
    p = ctypes.POINTER(CREDENTIAL)()
    if not _adv.CredReadW(PREFIX + key, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        c = p.contents
        return bytes(c.CredentialBlob[: c.CredentialBlobSize]).decode("utf-16-le")
    finally:
        _adv.CredFree(p)


def delete_secret(key):
    if not IS_WIN:
        _memory.pop(key, None)
        return
    _adv.CredDeleteW(PREFIX + key, CRED_TYPE_GENERIC, 0)
