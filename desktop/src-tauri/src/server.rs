//! The server that ships inside the app (BundledServer.swift on the Mac): started with the app, stopped when it
//! quits, and started again (a few times) if it dies. The same server as the Mac's, run the same way:
//! `python -m uvicorn core.server.app:app` in the bundled `app` folder, told where its data and web app are.

use std::fs::{File, OpenOptions};
use std::io::Write;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

use crate::config;
use crate::os::{ctrl_break, Job};

#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
/// The bundled Python, inside the app's resources.
#[cfg(windows)]
const PYTHON: &str = "python/python.exe";
#[cfg(not(windows))]
const PYTHON: &str = "python/bin/python3";
/// What the shell tells the web app it can do (core/server/computer.py); "updates" too when the updater is on.
pub const CAN: &str = "quit,reveal,login";
const LOG_LIMIT: u64 = 5_000_000;

/// Where things live inside the installed app (beside the program), as on the Mac: python/, app/ (core, modules,
/// app.json), ui/ (the built web app) and bin/ (helper programs, if the app has any).
#[derive(Clone, Debug)]
pub struct Bundled {
    pub python: PathBuf,
    pub app: PathBuf,
    pub ui: PathBuf,
    pub bin: PathBuf,
}

impl Bundled {
    /// The bundled server, if this build has one (a development build doesn't, and uses <PREFIX>_SERVER_URL).
    pub fn locate(resources: &Path) -> Option<Bundled> {
        let python = resources.join(PYTHON);
        if !python.is_file() {
            return None;
        }
        Some(Bundled { python, app: resources.join("app"), ui: resources.join("ui"), bin: resources.join("bin") })
    }
}

struct Inner {
    child: Option<Child>,
    stopping: bool,
    crashes: Vec<Instant>,
    failure: Option<String>,
}

pub struct Server {
    bundled: Bundled,
    inner: Mutex<Inner>,
    job: Option<Job>,
    can: String,
}

impl Server {
    pub fn new(bundled: Bundled, can: String) -> Arc<Server> {
        Arc::new(Server {
            bundled,
            can,
            inner: Mutex::new(Inner { child: None, stopping: false, crashes: Vec::new(), failure: None }),
            job: Job::new(),
        })
    }

    fn lock(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Why the server can't run, in words for the menu. None while all is well.
    pub fn failure(&self) -> Option<String> {
        self.lock().failure.clone()
    }

    pub fn is_running(&self) -> bool {
        let mut inner = self.lock();
        inner.child.as_mut().map(|c| matches!(c.try_wait(), Ok(None))).unwrap_or(false)
    }

    pub fn is_stopping(&self) -> bool {
        self.lock().stopping
    }

    pub fn start(self: &Arc<Self>, port: u16) -> Result<(), String> {
        let mut inner = self.lock();
        if let Some(child) = inner.child.as_mut() {
            if matches!(child.try_wait(), Ok(None)) {
                return Ok(());
            }
        }
        inner.stopping = false;
        inner.failure = None;

        let log_path = config::log_file();
        if let Some(logs) = log_path.parent() {
            std::fs::create_dir_all(logs).map_err(|e| format!("Couldn't make {}: {e}", logs.display()))?;
        }
        if std::fs::metadata(&log_path).map(|m| m.len() > LOG_LIMIT).unwrap_or(false) {
            let _ = std::fs::remove_file(&log_path); // keep the log from growing forever (nothing else holds it now)
        }
        let mut log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| format!("Couldn't open {}: {e}", log_path.display()))?;
        let _ = writeln!(log, "\n— {} server starting (unix time {}) —", config::NAME, unix_now());
        let err_log: File = log.try_clone().map_err(|e| e.to_string())?;

        let b = &self.bundled;
        let prefix = config::PREFIX;
        let mut command = Command::new(&b.python);
        command
            .args(["-m", "uvicorn", "core.server.app:app", "--host", "127.0.0.1", "--port", &port.to_string()])
            .current_dir(&b.app)
            .env_clear();
        for (key, value) in std::env::vars_os() {
            if !not_for_the_server(&key.to_string_lossy().to_uppercase()) {
                command.env(key, value);
            }
        }
        command
            .env("PATH", server_path(&b.bin))
            .env("PYTHONDONTWRITEBYTECODE", "1") // the app folder is never written to while it runs
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONUTF8", "1") // Windows would otherwise read and write files in its own code page
            .env(format!("{prefix}_DATA_DIR"), config::data_dir())
            .env(format!("{prefix}_UI_DIR"), &b.ui)
            .env(format!("{prefix}_PARENT_PID"), std::process::id().to_string())
            .env(format!("{prefix}_SHELL"), "desktop")
            .env(format!("{prefix}_SHELL_CAN"), &self.can)
            .stdin(Stdio::null())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(err_log));
        #[cfg(windows)]
        command.creation_flags(CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW);
        // A process group of its own, so stopping it stops anything it started too.
        #[cfg(unix)]
        command.process_group(0);
        let child = command.spawn().map_err(|e| format!("Couldn't start {}'s server ({e})", config::NAME))?;
        if let Some(job) = &self.job {
            job.assign(&child);
        }
        inner.child = Some(child);
        drop(inner);

        let server = self.clone();
        thread::Builder::new().name("server-watch".into()).spawn(move || server.watch(port)).map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Waits for the server to end, and starts it again unless it was stopped on purpose or keeps dying.
    fn watch(self: Arc<Self>, port: u16) {
        loop {
            thread::sleep(Duration::from_millis(250));
            let mut inner = self.lock();
            let Some(child) = inner.child.as_mut() else { return };
            if matches!(child.try_wait(), Ok(None)) {
                continue;
            }
            inner.child = None;
            if inner.stopping {
                return;
            }
            let now = Instant::now();
            inner.crashes.retain(|t| now.duration_since(*t) < Duration::from_secs(120));
            inner.crashes.push(now);
            if inner.crashes.len() >= 3 {
                inner.failure = Some(explain(port));
                return;
            }
            drop(inner);
            let _ = self.start(port); // start() watches the new one; this watcher is done
            return;
        }
    }

    /// Stops the server and waits (briefly) for it to finish what it's doing.
    pub fn stop(&self) {
        let mut inner = self.lock();
        inner.stopping = true;
        let Some(mut child) = inner.child.take() else { return };
        drop(inner);
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        let polite = ctrl_break(child.id());
        let deadline = Instant::now() + Duration::from_secs(if polite { 5 } else { 0 });
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(50));
        }
        #[cfg(unix)]
        crate::os::kill_group(child.id());
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// The last useful line of the server log, in plain words where we recognise it.
fn explain(port: u16) -> String {
    let path = config::log_file();
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    let tail: Vec<&str> = text.lines().rev().take(40).collect();
    let in_use = ["address already in use", "Errno 48", "Errno 98", "10048", "only one usage of each socket address"];
    if tail.iter().any(|l| in_use.iter().any(|m| l.contains(m))) {
        return format!("Another app is using port {port}, so {} can't start. Quit it, or change the port.", config::NAME);
    }
    let last = tail.iter().find(|l| !l.trim().is_empty() && !l.starts_with('—')).copied().unwrap_or("no details");
    let last: String = last.chars().take(120).collect();
    format!("{}'s server stopped unexpectedly ({last}). Log: {}", config::NAME, path.display())
}

/// The server's PATH: the app's own helpers first, then only the system's own folders.
#[cfg(windows)]
fn server_path(bin: &Path) -> String {
    let root = std::env::var("SystemRoot").unwrap_or_else(|_| "C:\\Windows".into());
    format!("{};{root}\\System32;{root}", bin.display())
}

#[cfg(not(windows))]
fn server_path(bin: &Path) -> String {
    format!("{}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", bin.display())
}

/// What of this app's environment the server doesn't get (upper-cased names): another Python's settings, and on
/// Linux what an AppImage sets up for its own GTK and libraries.
fn not_for_the_server(key: &str) -> bool {
    if key.starts_with("PYTHON") {
        return true;
    }
    cfg!(not(windows))
        && ["LD_", "GTK_", "GDK_", "GIO_", "GST_", "GSETTINGS_", "WEBKIT_", "APPDIR", "APPIMAGE", "OWD", "ARGV0"].iter().any(|p| key.starts_with(p))
}

fn unix_now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn another_pythons_settings_and_the_appimages_libraries_stay_behind() {
        assert!(not_for_the_server("PYTHONPATH"));
        assert!(!not_for_the_server("HOME"));
        assert_eq!(not_for_the_server("LD_LIBRARY_PATH"), cfg!(not(windows)));
    }
}
