from __future__ import annotations

import ctypes
from ctypes import wintypes


class _DataBlob(ctypes.Structure):
    _fields_ = (("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte)))


CRYPTPROTECT_UI_FORBIDDEN = 0x01


def protect(data: bytes) -> bytes:
    source_buffer=ctypes.create_string_buffer(data)
    source=_DataBlob(len(data),ctypes.cast(source_buffer,ctypes.POINTER(ctypes.c_byte)))
    result=_DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source),"NexTerm SSH key",None,None,None,CRYPTPROTECT_UI_FORBIDDEN,ctypes.byref(result)):
        raise ctypes.WinError()
    try:return ctypes.string_at(result.data,result.size)
    finally:ctypes.windll.kernel32.LocalFree(result.data)


def unprotect(data: bytes) -> bytes:
    source_buffer=ctypes.create_string_buffer(data)
    source=_DataBlob(len(data),ctypes.cast(source_buffer,ctypes.POINTER(ctypes.c_byte)))
    result=_DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source),None,None,None,None,CRYPTPROTECT_UI_FORBIDDEN,ctypes.byref(result)):
        raise ctypes.WinError()
    try:return ctypes.string_at(result.data,result.size)
    finally:ctypes.windll.kernel32.LocalFree(result.data)
