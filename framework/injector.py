"""DLL 注入模块（远线程 LoadLibraryW 方式）。

用法：
    injector.inject_dll(pid, dll_path)

说明：
- 这是标准的通用 DLL 注入实现，可以把你指定的任意 DLL 载入目标 QQ 进程。
- 真正与 NTQQ 内部交互的 hook DLL 需要由你自己提供（config.json -> inject.dll_path），
  框架在检测到 QQ 进程后会按配置自动完成注入。
- 注入 DLL 的位数必须与 QQ 进程一致（当前 NTQQ 为 64 位）。
"""
import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger("qq.injector")

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
INFINITE = 0xFFFFFFFF

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# 显式 64 位原型：否则指针返回值会被默认按 32 位 int 截断，写入非法地址
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.VirtualAllocEx.restype = wintypes.LPVOID
_kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                     ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
_kernel32.WriteProcessMemory.restype = wintypes.BOOL
_kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                         ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_kernel32.CreateRemoteThread.restype = wintypes.HANDLE
_kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                         wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.VirtualFreeEx.restype = wintypes.BOOL
_kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]


def _check(result, what: str):
    if not result:
        raise OSError(f"{what} 失败, WinError={ctypes.get_last_error()}")


def inject_dll(pid: int, dll_path: str) -> bool:
    """向目标进程注入 DLL，成功返回 True。dll_path 必须是绝对路径。"""
    dll_path = os.path.abspath(str(dll_path))
    buf = ctypes.create_unicode_buffer(dll_path)
    buf_bytes = ctypes.sizeof(buf)

    h_process = _kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    _check(h_process, f"OpenProcess(pid={pid})")
    try:
        remote_mem = _kernel32.VirtualAllocEx(
            h_process, None, buf_bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        _check(remote_mem, "VirtualAllocEx")

        written = ctypes.c_size_t(0)
        _check(_kernel32.WriteProcessMemory(
            h_process, remote_mem, buf, buf_bytes, ctypes.byref(written)),
            "WriteProcessMemory")

        h_thread = _kernel32.CreateRemoteThread(
            h_process, None, 0, _kernel32.LoadLibraryW, remote_mem, 0, None)
        _check(h_thread, "CreateRemoteThread")
        try:
            _kernel32.WaitForSingleObject(h_thread, INFINITE)
            exit_code = wintypes.DWORD(0)
            _kernel32.GetExitCodeThread(h_thread, ctypes.byref(exit_code))
        finally:
            _kernel32.CloseHandle(h_thread)

        _check(_kernel32.VirtualFreeEx(h_process, remote_mem, 0, MEM_RELEASE),
               "VirtualFreeEx")
        if not exit_code.value:
            raise OSError(
                f"DLL 在目标进程内加载失败（LoadLibraryW 返回 0）。"
                f"请确认路径存在且 DLL 位数与 QQ 一致: {dll_path}")
        log.info("DLL 注入完成: PID=%s DLL=%s 模块句柄=0x%x", pid, dll_path, exit_code.value)
        return True
    finally:
        _kernel32.CloseHandle(h_process)


def is_wow64(pid: int) -> bool:
    """判断目标进程是否为 32 位（运行在 WOW64 下）。"""
    h = _kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    _check(h, f"OpenProcess(pid={pid})")
    try:
        is_wow = wintypes.BOOL(False)
        _kernel32.IsWow64Process(h, ctypes.byref(is_wow))
        return bool(is_wow.value)
    finally:
        _kernel32.CloseHandle(h)
