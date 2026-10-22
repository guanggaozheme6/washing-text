/* WashingText.exe —— 桌面启动器外壳 (纯 Win32, 无运行时依赖)
 *
 * 职责只有一件事: 在自己所在目录里找 python\pythonw.exe,
 * 以 app\ 为工作目录拉起 app\launcher.py, 然后自己退出.
 *
 * 有了这个 exe:
 *   - 用户双击的就是"一个应用", 不再是"指向解释器的快捷方式";
 *   - 文件管理器/任务栏里显示的是应用自己的图标;
 *   - 想再打开时直接双击它, 跟双击桌面快捷方式等效.
 *
 * 编译 (详见 build/compile_exe.cmd):
 *   windres exe_launcher.rc -O coff -o exe_launcher.res
 *   gcc -municode -mwindows -O2 -o WashingText.exe exe_launcher.c exe_launcher.res -static
 */
#include <windows.h>
#include <wchar.h>

#define APP_TITLE L"文本改写降重工作台"

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR pCmdLine, int nShow)
{
    WCHAR dir[MAX_PATH];
    WCHAR cmdline[MAX_PATH * 2];
    WCHAR cwd[MAX_PATH];
    WCHAR *slash;
    DWORD n;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;

    (void)hInst; (void)hPrev; (void)pCmdLine; (void)nShow;

    n = GetModuleFileNameW(NULL, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) {
        goto fail;
    }
    slash = wcsrchr(dir, L'\\');
    if (slash == NULL) {
        goto fail;
    }
    *slash = L'\0';

    wsprintfW(cwd, L"%s\\app", dir);
    wsprintfW(cmdline, L"\"%s\\python\\pythonw.exe\" \"%s\\app\\launcher.py\"", dir, dir);

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    /* launcher.py 自己会处理"服务已在跑"的情况, 这里只管把进程拉起来 */
    if (!CreateProcessW(NULL, cmdline, NULL, NULL, FALSE, 0, NULL, cwd, &si, &pi)) {
        goto fail;
    }
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;

fail:
    MessageBoxW(NULL,
                L"启动失败：找不到程序目录里的 python\\pythonw.exe。\n\n"
                L"请重新安装；若反复失败，请查看日志：\n"
                L"%APPDATA%\\WashingText\\logs\\web.log",
                APP_TITLE, MB_ICONERROR | MB_OK);
    return 1;
}
