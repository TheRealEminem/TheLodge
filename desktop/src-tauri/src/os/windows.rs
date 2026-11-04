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
