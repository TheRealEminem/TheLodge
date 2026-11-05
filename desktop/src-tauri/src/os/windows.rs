//! The few plain Win32 calls the shell needs, declared here so they don't depend on a version of the `windows`
//! crate (taken from Trailmix's win.rs): a job object that takes the server down with the app, a Ctrl+Break for
//! stopping it politely, and the registry values open at login uses.

use std::ffi::c_void;
use std::os::windows::io::AsRawHandle;

#[repr(C)]
#[derive(Default)]
struct JobBasicLimits {
    per_process_user_time: i64,
    per_job_user_time: i64,
    limit_flags: u32,
    min_working_set: usize,
    max_working_set: usize,
    active_process_limit: u32,
    affinity: usize,
    priority_class: u32,
    scheduling_class: u32,
}

#[repr(C)]
#[derive(Default)]
struct JobExtendedLimits {
    basic: JobBasicLimits,
    io: [u64; 6],
    process_memory_limit: usize,
    job_memory_limit: usize,
    peak_process_memory: usize,
    peak_job_memory: usize,
}

const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: i32 = 9;
const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x2000;
const CTRL_BREAK_EVENT: u32 = 1;
const REG_SZ: u32 = 1;
const RRF_RT_REG_SZ: u32 = 0x0000_0002;
const RRF_RT_REG_BINARY: u32 = 0x0000_0008;

#[link(name = "kernel32")]
extern "system" {
    fn CreateJobObjectW(attributes: *const c_void, name: *const u16) -> *mut c_void;
    fn SetInformationJobObject(job: *mut c_void, class: i32, info: *const c_void, len: u32) -> i32;
    fn AssignProcessToJobObject(job: *mut c_void, process: *mut c_void) -> i32;
    fn CloseHandle(handle: *mut c_void) -> i32;
    fn AttachConsole(pid: u32) -> i32;
    fn FreeConsole() -> i32;
    fn GenerateConsoleCtrlEvent(event: u32, group: u32) -> i32;
    fn SetConsoleCtrlHandler(handler: *const c_void, add: i32) -> i32;
}

#[link(name = "advapi32")]
extern "system" {
    fn RegSetKeyValueW(key: *mut c_void, subkey: *const u16, value: *const u16, kind: u32, data: *const c_void, len: u32) -> i32;
    fn RegDeleteKeyValueW(key: *mut c_void, subkey: *const u16, value: *const u16) -> i32;
    fn RegGetValueW(key: *mut c_void, subkey: *const u16, value: *const u16, flags: u32, kind: *mut u32, data: *mut c_void, len: *mut u32) -> i32;
}

/// A job object with "kill on close": processes put in it end when this app does, however it ends.
pub struct Job(*mut c_void);

unsafe impl Send for Job {}
unsafe impl Sync for Job {}

impl Job {
    pub fn new() -> Option<Job> {
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return None;
            }
            let mut limits = JobExtendedLimits::default();
            limits.basic.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                &limits as *const JobExtendedLimits as *const c_void,
                std::mem::size_of::<JobExtendedLimits>() as u32,
            );
            if ok == 0 {
                CloseHandle(job);
                return None;
            }
            Some(Job(job))
        }
    }

    pub fn assign(&self, child: &std::process::Child) -> bool {
        unsafe { AssignProcessToJobObject(self.0, child.as_raw_handle()) != 0 }
    }
}

impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

/// Asks the server to stop as Ctrl+C would (uvicorn finishes what it's doing, then quits). It was started in a
/// process group of its own with no window, so the event goes to it alone. False if that couldn't be sent.
pub fn ctrl_break(pid: u32) -> bool {
    unsafe {
        FreeConsole();
        if AttachConsole(pid) == 0 {
            return false;
        }
        // Not for us: the event goes to the server's process group, but ignore it here too, to be safe.
        SetConsoleCtrlHandler(std::ptr::null(), 1);
        let sent = GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid) != 0;
        FreeConsole();
        sent
    }
}

fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

/// HKEY_CURRENT_USER: ((HKEY)(ULONG_PTR)((LONG)0x80000001)), sign-extended on 64-bit Windows.
fn hkcu() -> *mut c_void {
    0x8000_0001u32 as i32 as isize as *mut c_void
}

/// A text value under HKEY_CURRENT_USER, if it's there.
pub fn reg_get_string(subkey: &str, value: &str) -> Option<String> {
    let (subkey, value) = (wide(subkey), wide(value));
    unsafe {
        let mut len: u32 = 0;
        if RegGetValueW(hkcu(), subkey.as_ptr(), value.as_ptr(), RRF_RT_REG_SZ, std::ptr::null_mut(), std::ptr::null_mut(), &mut len) != 0 {
            return None;
        }
        let mut buffer = vec![0u16; (len as usize / 2) + 1];
        let mut len = (buffer.len() * 2) as u32;
        if RegGetValueW(hkcu(), subkey.as_ptr(), value.as_ptr(), RRF_RT_REG_SZ, std::ptr::null_mut(), buffer.as_mut_ptr() as *mut c_void, &mut len) != 0 {
            return None;
        }
        let end = buffer.iter().position(|&c| c == 0).unwrap_or(buffer.len());
        Some(String::from_utf16_lossy(&buffer[..end]))
    }
}

/// A binary value under HKEY_CURRENT_USER, if it's there.
pub fn reg_get_binary(subkey: &str, value: &str) -> Option<Vec<u8>> {
    let (subkey, value) = (wide(subkey), wide(value));
    unsafe {
        let mut len: u32 = 0;
        if RegGetValueW(hkcu(), subkey.as_ptr(), value.as_ptr(), RRF_RT_REG_BINARY, std::ptr::null_mut(), std::ptr::null_mut(), &mut len) != 0 {
            return None;
        }
        let mut buffer = vec![0u8; len as usize];
        if RegGetValueW(hkcu(), subkey.as_ptr(), value.as_ptr(), RRF_RT_REG_BINARY, std::ptr::null_mut(), buffer.as_mut_ptr() as *mut c_void, &mut len) != 0 {
            return None;
        }
        buffer.truncate(len as usize);
        Some(buffer)
    }
}

/// Sets a text value under HKEY_CURRENT_USER (making the key if needed).
pub fn reg_set_string(subkey: &str, value: &str, data: &str) -> bool {
    let (subkey, value, data) = (wide(subkey), wide(value), wide(data));
    unsafe { RegSetKeyValueW(hkcu(), subkey.as_ptr(), value.as_ptr(), REG_SZ, data.as_ptr() as *const c_void, (data.len() * 2) as u32) == 0 }
}

/// Removes a value under HKEY_CURRENT_USER. True if it's gone (or wasn't there).
pub fn reg_delete(subkey: &str, value: &str) -> bool {
    let (subkey, value) = (wide(subkey), wide(value));
    let status = unsafe { RegDeleteKeyValueW(hkcu(), subkey.as_ptr(), value.as_ptr()) };
    status == 0 || status == 2 // ERROR_FILE_NOT_FOUND
}

// MARK: Processes by path, version resources and a question (the updater)

#[repr(C)]
struct ProcessEntry32W {
    size: u32,
    usage: u32,
    pid: u32,
    default_heap: usize,
    module: u32,
    threads: u32,
    parent: u32,
    priority: i32,
    flags: u32,
    exe: [u16; 260],
}

const TH32CS_SNAPPROCESS: u32 = 0x2;
const SYNCHRONIZE: u32 = 0x0010_0000;
const PROCESS_TERMINATE: u32 = 0x0001;
const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
const WAIT_OBJECT_0: u32 = 0;
const MB_YESNO: u32 = 0x0000_0004;
const MB_ICONQUESTION: u32 = 0x0000_0020;
const MB_SETFOREGROUND: u32 = 0x0001_0000;
const IDYES: i32 = 6;

#[link(name = "kernel32")]
extern "system" {
    fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> *mut c_void;
    fn Process32FirstW(snapshot: *mut c_void, entry: *mut ProcessEntry32W) -> i32;
    fn Process32NextW(snapshot: *mut c_void, entry: *mut ProcessEntry32W) -> i32;
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut c_void;
    fn WaitForSingleObject(handle: *mut c_void, millis: u32) -> u32;
    fn TerminateProcess(process: *mut c_void, code: u32) -> i32;
    fn QueryFullProcessImageNameW(process: *mut c_void, flags: u32, name: *mut u16, size: *mut u32) -> i32;
}

#[link(name = "version")]
extern "system" {
    fn GetFileVersionInfoSizeW(path: *const u16, handle: *mut u32) -> u32;
    fn GetFileVersionInfoW(path: *const u16, handle: u32, len: u32, data: *mut c_void) -> i32;
    fn VerQueryValueW(block: *const c_void, sub_block: *const u16, buffer: *mut *mut c_void, len: *mut u32) -> i32;
}

#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(window: *mut c_void, text: *const u16, caption: *const u16, kind: u32) -> i32;
}

fn wide_path(path: &std::path::Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    path.as_os_str().encode_wide().chain(std::iter::once(0)).collect()
}

/// Every running process's id.
fn process_ids() -> Vec<u32> {
    let mut out = Vec::new();
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snapshot.is_null() || snapshot as isize == -1 {
            return out;
        }
        let mut entry: ProcessEntry32W = std::mem::zeroed();
        entry.size = std::mem::size_of::<ProcessEntry32W>() as u32;
        if Process32FirstW(snapshot, &mut entry) != 0 {
            loop {
                out.push(entry.pid);
                if Process32NextW(snapshot, &mut entry) == 0 {
                    break;
                }
            }
        }
        CloseHandle(snapshot);
    }
    out
}

fn process_path(pid: u32) -> Option<std::path::PathBuf> {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return None;
        }
        let mut buffer = vec![0u16; 1024];
        let mut size = buffer.len() as u32;
        let ok = QueryFullProcessImageNameW(handle, 0, buffer.as_mut_ptr(), &mut size) != 0;
        CloseHandle(handle);
        ok.then(|| std::path::PathBuf::from(String::from_utf16_lossy(&buffer[..size as usize])))
    }
}

/// Waits for a process to end. True if it did (or was already gone).
pub fn wait_for_exit(pid: u32, timeout: std::time::Duration) -> bool {
    unsafe {
        let handle = OpenProcess(SYNCHRONIZE, 0, pid);
        if handle.is_null() {
            return true;
        }
        let done = WaitForSingleObject(handle, timeout.as_millis().min(0xFFFF_FFFE) as u32) == WAIT_OBJECT_0;
        CloseHandle(handle);
        done
    }
}

/// The processes (other than this one) running a program from inside `folder`: the app and its server's Python.
pub fn processes_in(folder: &std::path::Path) -> Vec<u32> {
    // Compared in full, long form (a short C:\Users\RUNNER~1\... and its long name are the same folder).
    let normal = |p: &std::path::Path| std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf()).to_string_lossy().to_lowercase();
    let folder = normal(folder).trim_end_matches('\\').to_string() + "\\";
    let me = std::process::id();
    process_ids()
        .into_iter()
        .filter(|&pid| pid != me && pid != 0)
        .filter(|&pid| process_path(pid).map(|path| normal(&path).starts_with(&folder)).unwrap_or(false))
        .collect()
}

pub fn terminate(pid: u32) -> bool {
    unsafe {
        let handle = OpenProcess(PROCESS_TERMINATE, 0, pid);
        if handle.is_null() {
            return false;
        }
        let ok = TerminateProcess(handle, 1) != 0;
        CloseHandle(handle);
        ok
    }
}

/// A string from a file's version resource ("ProductName", "ProductVersion"…), in whichever language it has.
pub fn version_string(file: &std::path::Path, name: &str) -> Option<String> {
    let path = wide_path(file);
    unsafe {
        let mut ignored: u32 = 0;
        let size = GetFileVersionInfoSizeW(path.as_ptr(), &mut ignored);
        if size == 0 {
            return None;
        }
        let mut block = vec![0u8; size as usize];
        if GetFileVersionInfoW(path.as_ptr(), 0, size, block.as_mut_ptr() as *mut c_void) == 0 {
            return None;
        }
        let base = block.as_ptr() as *const c_void;
        let mut languages: Vec<String> = Vec::new();
        let mut pointer: *mut c_void = std::ptr::null_mut();
        let mut len: u32 = 0;
        let translation = wide("\\VarFileInfo\\Translation");
        if VerQueryValueW(base, translation.as_ptr(), &mut pointer, &mut len) != 0 && !pointer.is_null() {
            let pairs = std::slice::from_raw_parts(pointer as *const u16, (len / 2) as usize);
            for pair in pairs.chunks(2) {
                if pair.len() == 2 {
                    languages.push(format!("{:04x}{:04x}", pair[0], pair[1]));
                }
            }
        }
        languages.extend(["040904b0".to_string(), "040904e4".to_string(), "04090000".to_string()]);
        for language in languages {
            let query = wide(&format!("\\StringFileInfo\\{language}\\{name}"));
            let mut pointer: *mut c_void = std::ptr::null_mut();
            let mut len: u32 = 0;
            if VerQueryValueW(base, query.as_ptr(), &mut pointer, &mut len) != 0 && !pointer.is_null() && len > 0 {
                let chars = std::slice::from_raw_parts(pointer as *const u16, len as usize);
                let end = chars.iter().position(|&c| c == 0).unwrap_or(chars.len());
                return Some(String::from_utf16_lossy(&chars[..end]).trim().to_string());
            }
        }
        None
    }
}

/// Asks a yes-or-no question in a Windows message box. True for Yes.
pub fn ask(title: &str, text: &str) -> bool {
    let (title, text) = (wide(title), wide(text));
    unsafe { MessageBoxW(std::ptr::null_mut(), text.as_ptr(), title.as_ptr(), MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND) == IDYES }
}
