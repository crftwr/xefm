/*
 * xefmctl.c - xefmctl.exe, the launcher the Store (MSIX) package's app
 * execution alias names (#983)
 *
 * A console-subsystem executable that runs the bundle's embedded interpreter
 * as `python.exe -I app\xefm\remote_cli.py`, forwarding its own arguments,
 * standard handles and exit code. It is what the xefmctl.cmd shim XeFM writes
 * (xefm/remote_server.py) does on every other install.
 *
 * WHY AN EXECUTABLE. On the Store install, nothing inside the package can be
 * started by a process outside it: every path under
 * C:\Program Files\WindowsApps refuses CreateProcess with "Access is denied"
 * (STATUS_ACCESS_DENIED), although the files stay readable, because those
 * binaries may only be started with the package's own identity. And no shell
 * XeFM starts has it: Windows starts a child whose program lies outside the
 * package (cmd.exe, pwsh.exe, bash.exe) without the identity, so from every
 * shell the shim's runtime\python.exe was refused. (A child inside the
 * package, as XeFM starting runtime\python.exe for a PROGRAMS entry, keeps
 * it.)
 *
 * The supported way in is an app execution alias: the package declares one
 * (windows.appExecutionAlias, see build_msix.ps1), Windows puts a stub in
 * %LOCALAPPDATA%\Microsoft\WindowsApps, and launching the stub starts the
 * target with the package's identity - which may then run python.exe out of
 * the package. An alias can only name an .exe in the package, under the same
 * file name, and cannot carry arguments, so `-I app\xefm\remote_cli.py` has
 * to be baked into a real executable. This is it. Keyhac's
 * keyhac-mcp-bridge.exe is the same thing for the same reason.
 *
 * Bundle layout it assumes, relative to its own directory = <root>:
 *   <root>\xefmctl.exe                this launcher
 *   <root>\runtime\python.exe         embedded CPython (console interpreter)
 *   <root>\app\xefm\remote_cli.py     the client: standard library only
 *
 * -I (isolated mode) as the shim passes it: the client imports only the
 * standard library and loads the command table by path, so nothing on
 * PYTHONPATH or in the working directory may shadow a module.
 */

#define WIN32_LEAN_AND_MEAN
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#include <stdio.h>   /* fwprintf, _snwprintf_s */
#include <wchar.h>   /* wcsrchr */

/* Longest path or command line we build. */
#define XEFMCTL_PATH_MAX 32768

/* Exit status 3: XeFM cannot be reached (doc/XEFMCTL_FEATURE.md). */
static int fail(const wchar_t *what, DWORD code)
{
    fwprintf(stderr, L"xefmctl: %ls (error %lu)\n", what, code);
    return 3;
}

/*
 * The tail of our command line, past argv[0] - forwarded to Python verbatim
 * rather than rebuilt from an argv, so the caller's quoting survives intact.
 */
static const wchar_t *arguments_after_program(const wchar_t *cmdline)
{
    const wchar_t *cursor = cmdline;

    if (*cursor == L'"') {
        cursor++;
        while (*cursor && *cursor != L'"') { cursor++; }
        if (*cursor == L'"') { cursor++; }
    } else {
        while (*cursor && *cursor != L' ' && *cursor != L'\t') { cursor++; }
    }
    while (*cursor == L' ' || *cursor == L'\t') { cursor++; }
    return cursor;
}

/*
 * Ctrl-C reaches every process on the console, the interpreter included, and
 * the client handles it (a search ends and closes its connection). We only
 * wait for the interpreter to finish and pass its status on. A handler, not
 * SetConsoleCtrlHandler(NULL, TRUE): that one is inherited, and the
 * interpreter would then ignore Ctrl-C too.
 */
static BOOL WINAPI wait_for_child(DWORD event)
{
    return event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT;
}

int wmain(void)
{
    wchar_t root[XEFMCTL_PATH_MAX];
    wchar_t commandLine[XEFMCTL_PATH_MAX];
    wchar_t *lastSlash;
    const wchar_t *arguments;
    STARTUPINFOW startup;
    PROCESS_INFORMATION child;
    HANDLE job;
    DWORD status = 3;

    /* <root>, with its trailing backslash, from our own image path. */
    DWORD length = GetModuleFileNameW(NULL, root, XEFMCTL_PATH_MAX);
    if (length == 0 || length >= XEFMCTL_PATH_MAX) {
        return fail(L"cannot determine my own path", GetLastError());
    }
    lastSlash = wcsrchr(root, L'\\');
    if (lastSlash == NULL) {
        return fail(L"my own path has no directory", 0);
    }
    lastSlash[1] = L'\0';

    arguments = arguments_after_program(GetCommandLineW());
    _snwprintf_s(commandLine, XEFMCTL_PATH_MAX, _TRUNCATE,
                 L"\"%lsruntime\\python.exe\" -I \"%lsapp\\xefm\\remote_cli.py\"%ls%ls",
                 root, root, *arguments ? L" " : L"", arguments);

    SetConsoleCtrlHandler(wait_for_child, TRUE);

    /* A job with KILL_ON_JOB_CLOSE so the interpreter cannot outlive us if we
     * are terminated. Created suspended so it is in the job before it runs;
     * a job that cannot be made only costs that guarantee. */
    job = CreateJobObjectW(NULL, NULL);
    if (job != NULL) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
        ZeroMemory(&limits, sizeof(limits));
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                &limits, sizeof(limits));
    }

    ZeroMemory(&startup, sizeof(startup));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput  = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError  = GetStdHandle(STD_ERROR_HANDLE);
    ZeroMemory(&child, sizeof(child));

    if (!CreateProcessW(NULL, commandLine, NULL, NULL, TRUE,
                        CREATE_SUSPENDED, NULL, NULL, &startup, &child)) {
        DWORD failure = GetLastError();
        if (job != NULL) { CloseHandle(job); }
        return fail(L"cannot start the bundled interpreter (runtime\\python.exe)",
                    failure);
    }
    if (job != NULL) { AssignProcessToJobObject(job, child.hProcess); }
    ResumeThread(child.hThread);

    WaitForSingleObject(child.hProcess, INFINITE);
    if (!GetExitCodeProcess(child.hProcess, &status)) { status = 3; }

    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    if (job != NULL) { CloseHandle(job); }
    return (int)status;
}
