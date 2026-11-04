//! What the shell needs of Linux (and of a Mac, for development runs): stopping the server and what it started,
//! and, before the window exists, choosing how WebKitGTK draws.

/// Keeps the server from outliving the app. On Windows a job object does it; here the server watches for its
/// parent going (<PREFIX>_PARENT_PID, core/server/app.py), so there's nothing to hold.
pub struct Job;

impl Job {
    pub fn new() -> Option<Job> {
        Some(Job)
    }

    pub fn assign(&self, _child: &std::process::Child) -> bool {
        true
    }
}

/// Asks the server (and its process group) to stop: SIGTERM, which uvicorn takes as "finish up and quit".
pub fn ctrl_break(pid: u32) -> bool {
    unsafe { libc::kill(-(pid as i32), libc::SIGTERM) == 0 || libc::kill(pid as i32, libc::SIGTERM) == 0 }
}

/// Ends a process group at once (the server's, when it didn't stop when asked).
pub fn kill_group(pid: u32) {
    unsafe {
        libc::kill(-(pid as i32), libc::SIGKILL);
    }
}

/// Before GTK starts. WebKitGTK's DMA-BUF renderer leaves the window blank in virtual machines, with NVIDIA's
/// own driver, and where there's no GPU render node, so it's turned off there, and only there: turned off for
/// everyone, every page is drawn by the CPU (Trailmix scrolled at 5 frames a second that way).
#[cfg(target_os = "linux")]
pub fn before_window() {
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_some() {
        return;
    }
    if in_virtual_machine() || nvidia_driver() || !has_render_node() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
}

#[cfg(target_os = "linux")]
fn in_virtual_machine() -> bool {
    let cpu = std::fs::read_to_string("/proc/cpuinfo").unwrap_or_default();
    if cpu.lines().any(|l| l.starts_with("flags") && l.split_whitespace().any(|f| f == "hypervisor")) {
        return true;
    }
    let product = ["/sys/class/dmi/id/product_name", "/sys/class/dmi/id/sys_vendor"]
        .iter()
        .map(|p| std::fs::read_to_string(p).unwrap_or_default().to_lowercase())
        .collect::<String>();
    ["virtualbox", "vmware", "qemu", "kvm", "parallels", "utm", "hyper-v", "xen"].iter().any(|v| product.contains(v))
}

#[cfg(target_os = "linux")]
fn nvidia_driver() -> bool {
    std::path::Path::new("/proc/driver/nvidia").exists() || std::path::Path::new("/sys/module/nvidia").exists()
}

#[cfg(target_os = "linux")]
fn has_render_node() -> bool {
    std::fs::read_dir("/dev/dri")
        .map(|entries| entries.flatten().any(|e| e.file_name().to_string_lossy().starts_with("renderD")))
        .unwrap_or(false)
}
