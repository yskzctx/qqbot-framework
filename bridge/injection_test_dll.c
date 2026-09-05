#include <windows.h>

/* 无害注入测试：被加载后仅写一个标记文件，不调用任何 QQ 功能 */
DWORD WINAPI worker(LPVOID arg) {
    char path[MAX_PATH];
    GetTempPathA(MAX_PATH, path);
    lstrcatA(path, "qqbot_inject_ok.txt");
    HANDLE f = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
    if (f != INVALID_HANDLE_VALUE) {
        DWORD written;
        const char *msg = "injected into QQ OK";
        WriteFile(f, msg, lstrlenA(msg), &written, NULL);
        CloseHandle(f);
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        CreateThread(NULL, 0, worker, NULL, 0, NULL);
    }
    return TRUE;
}
