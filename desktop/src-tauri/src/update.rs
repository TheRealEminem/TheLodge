//! Keeps the app up to date from its GitHub releases (Updater.swift on the Mac, which this mirrors): looks a little
//! after launch and every 6 hours; on request downloads the new installer, checks it against the SHA-256 published
//! beside it and that it's this app's installer of that version, then quits and lets a copy of this program
//! (`--apply-update`) run it silently over the install once the app and its server are gone, and open the new
//! version. Go back installs the version this one replaced the same checked way, and skips this one until a newer
//! version is out. The data stays: migrations only add, so the older version opens it too.
//!
//! As on the Mac: beta updates (pre-releases) only when you turn them on, Skip this version, nothing looks or downloads
//! under Lockdown (or while the server can't say whether it's on), and nothing installs while the server is in the
//! middle of something.
//!
//! A release counts when it has this computer's installer, "<Slug>-<version>-windows-<arch>.exe", with its
//! ".sha256" beside it (scripts/build-windows.py makes both). The installer is unsigned, so there's no Authenticode
//! check yet: what's checked is the name, the published checksum and the installer's own version resource.
//!
//! For tests (the Mac's names): <PREFIX>_UPDATE_URL (the releases to look at), <PREFIX>_UPDATE_DELAY (seconds before
//! the first look), <PREFIX>_UPDATE_TEST=install|go-back (do it after the first look, without asking) and
//! <PREFIX>_UPDATE_NO_RELAUNCH. Logs go to logs/update.log in the data folder.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
#[cfg(windows)]
use std::io::Read;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
#[cfg(windows)]
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
#[cfg(windows)]
use std::time::Instant;

use serde_json::{json, Value};
#[cfg(windows)]
use sha2::{Digest, Sha256};

use crate::config;
#[cfg(windows)]
use crate::os;

pub const APPLY_FLAG: &str = "--apply-update";

/// This computer's kind, as release installers are named.
#[cfg(target_arch = "aarch64")]
pub const ARCH: &str = "arm64";
#[cfg(not(target_arch = "aarch64"))]
pub const ARCH: &str = "x64";

#[cfg(windows)]
const DETACHED_PROCESS: u32 = 0x0000_0008;
#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
const CREATE_BREAKAWAY_FROM_JOB: u32 = 0x0100_0000;

#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(not(windows), allow(dead_code))] // (Installing: only Windows installs, so far)
pub enum State {
    Idle,
    Checking,
    UpToDate,
    /// Couldn't reach GitHub to check.
    Offline,
    /// Lockdown is on: no looks, no downloads.
    LockedDown,
    Available(String),
    Downloading(String, Option<f64>),
    Installing(String),
    GoingBack(String),
    Failed(String),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Release {
    pub version: String,
    pub prerelease: bool,
    pub notes: Option<String>,
    /// The installer's file name, and where to download it and its checksum.
    pub name: String,
    pub installer: String,
    pub checksum: String,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Attempt {
    Install,
    GoBack,
}

/// What's remembered between launches: updates.json in the data folder.
#[derive(Clone, Debug, Default, PartialEq)]
struct Saved {
    /// Beta updates: also offer pre-releases. Off unless you turn it on.
    beta: bool,
    /// A version not to offer again (you skipped it, or went back from it). Newer ones are offered as usual.
    skipped: Option<String>,
    /// The version the last update replaced: Go back returns to it.
    previous: Option<String>,
    /// Why the last install didn't happen (written by --apply-update), shown once.
    last_error: Option<String>,
}

impl Saved {
    fn path() -> PathBuf {
        config::data_dir().join("updates.json")
    }

    fn load() -> Saved {
        let value: Value = fs::read_to_string(Self::path()).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null);
        let text = |key: &str| value.get(key).and_then(|v| v.as_str()).map(String::from);
        Saved {
            beta: value.get("beta").and_then(|v| v.as_bool()).unwrap_or(false),
            skipped: text("skipped"),
            previous: text("previous"),
            last_error: text("last_error"),
        }
    }

    fn save(&self) {
        let _ = fs::create_dir_all(config::data_dir());
        let value = json!({"beta": self.beta, "skipped": self.skipped, "previous": self.previous, "last_error": self.last_error});
        if let Ok(text) = serde_json::to_string_pretty(&value) {
            let _ = fs::write(Self::path(), text);
        }
    }
}

struct Inner {
    state: State,
    releases: Vec<Release>,
    latest: Option<Release>,
    checked_at: Option<u64>,
    last_try: Option<Attempt>,
    saved: Saved,
}

type Hook = Arc<dyn Fn() + Send + Sync>;

pub struct Updater {
    inner: Mutex<Inner>,
    current: String,
    exe: PathBuf,
    checking: AtomicBool,
    changed: Mutex<Vec<Hook>>,
    quit: Mutex<Option<Hook>>,
}

impl Updater {
    pub fn new(current: String, exe: PathBuf) -> Arc<Updater> {
        let mut saved = Saved::load();
        let mut state = State::Idle;
        if let Some(why) = saved.last_error.take() {
            state = State::Failed(why);
            saved.save();
        }
        Arc::new(Updater {
            inner: Mutex::new(Inner { state, releases: Vec::new(), latest: None, checked_at: None, last_try: None, saved }),
            current,
            exe,
            checking: AtomicBool::new(false),
            changed: Mutex::new(Vec::new()),
            quit: Mutex::new(None),
        })
    }

    /// Only an installed app (the installer put it there, with its uninstaller beside it) updates itself, and only
    /// with somewhere to look: the repo in app.json, or <PREFIX>_UPDATE_URL (tests).
    pub fn enabled_for(exe: &Path) -> bool {
        let installed = exe.parent().map(|dir| dir.join("uninstall.exe").is_file()).unwrap_or(false);
        cfg!(windows) && installed && feed().is_some()
    }

    fn lock(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Called (on whatever thread) whenever what Settings → Updates would show changes.
    pub fn observe(&self, f: impl Fn() + Send + Sync + 'static) {
        self.changed.lock().unwrap_or_else(|e| e.into_inner()).push(Arc::new(f));
    }

    /// How the app quits for an install (stopping its server first).
    pub fn set_quit(&self, f: impl Fn() + Send + Sync + 'static) {
        *self.quit.lock().unwrap_or_else(|e| e.into_inner()) = Some(Arc::new(f));
    }

    fn notify(&self) {
        let hooks: Vec<Hook> = self.changed.lock().unwrap_or_else(|e| e.into_inner()).clone();
        for f in hooks {
            f();
        }
    }

    fn set_state(&self, state: State) {
        log(&format!("{state:?}"));
        self.lock().state = state;
        self.notify();
    }

    pub fn state(&self) -> State {
        self.lock().state.clone()
    }

    /// Downloading, installing or going back: nothing else starts meanwhile.
    pub fn working(&self) -> bool {
        matches!(self.state(), State::Downloading(..) | State::Installing(_) | State::GoingBack(_))
    }

    /// Looks a little after launch (<PREFIX>_UPDATE_DELAY seconds, 20 by default), once the app's server answers,
    /// and every 6 hours. Not before the server: until it answers, Lockdown can't be read (and would read as off),
    /// and nothing would wait for its work to finish.
    pub fn begin(self: &Arc<Self>) {
        clean_old_downloads();
        let delay: f64 = config::env("UPDATE_DELAY").and_then(|d| d.parse().ok()).unwrap_or(20.0);
        let updater = self.clone();
        let _ = thread::Builder::new().name("updater".into()).spawn(move || {
            thread::sleep(Duration::from_secs_f64(delay.max(0.0)));
            let base = config::server_url();
            for _ in 0..600 {
                if config::answering(&base) {
                    break;
                }
                thread::sleep(Duration::from_millis(500));
            }
            updater.check(false);
            match config::env("UPDATE_TEST").as_deref() {
                Some("install") => updater.install(),
                Some("go-back") => updater.go_back(),
                _ => {}
            }
            loop {
                thread::sleep(Duration::from_secs(6 * 3600));
                updater.check(false);
            }
        });
    }

    /// Looks for a new version on another thread.
    pub fn check_soon(self: &Arc<Self>, manual: bool) {
        let updater = self.clone();
        thread::spawn(move || updater.check(manual));
    }

    /// Looks for a new version. `manual`: you asked (Check for updates…), so it shows "Checking…" meanwhile. Nothing
    /// goes out under Lockdown, or while the server can't say whether it's on.
    pub fn check(&self, manual: bool) {
        let Some(feed) = feed() else { return };
        if self.working() {
            return;
        }
        match lockdown_on() {
            Some(true) => {
                self.set_state(State::LockedDown);
                return;
            }
            None => {
                if manual {
                    self.set_state(State::Failed(format!("Couldn't ask {} whether Lockdown is on, so it didn't check.", config::NAME)));
                }
                log("couldn't read Lockdown from the server, so didn't look for updates");
                return;
            }
            Some(false) => {
                if self.state() == State::LockedDown {
                    let latest = self.lock().latest.as_ref().map(|l| l.version.clone());
                    self.set_state(latest.map_or(State::Idle, State::Available));
                }
            }
        }
        if self.checking.swap(true, Ordering::SeqCst) {
            return; // one look at a time
        }
        if manual && self.lock().latest.is_none() {
            self.set_state(State::Checking);
        }
        let found = fetch_json(&feed, &self.current);
        self.checking.store(false, Ordering::SeqCst);
        let Some(parsed) = found else {
            let offline = {
                let inner = self.lock();
                inner.latest.is_none() && (manual || inner.state == State::Checking)
            };
            if offline {
                self.set_state(State::Offline);
            }
            log(&format!("couldn't look for updates at {feed}"));
            return;
        };
        {
            let mut inner = self.lock();
            inner.releases = releases(&parsed);
            inner.checked_at = Some(now());
        }
        self.refresh();
    }

    /// Works out what to offer from the releases last seen, after a look or when a choice changes.
    fn refresh(&self) {
        {
            let mut inner = self.lock();
            if inner.checked_at.is_none() || matches!(inner.state, State::Downloading(..) | State::Installing(_) | State::GoingBack(_)) {
                return;
            }
            let latest = offer(&inner.releases, &self.current, inner.saved.beta, inner.saved.skipped.as_deref());
            inner.state = latest.as_ref().map(|r| State::Available(r.version.clone())).unwrap_or(State::UpToDate);
            inner.latest = latest;
        }
        self.notify();
    }

    // MARK: Your choices

    pub fn beta(&self) -> bool {
        self.lock().saved.beta
    }

    pub fn set_beta(self: &Arc<Self>, on: bool) {
        self.save(|s| s.beta = on);
        self.check_soon(false); // a fresh look, since betas come out more often
    }

    /// Skip this version: not offered again; newer ones are.
    pub fn skip(&self) {
        if self.working() {
            return;
        }
        let latest = self.lock().latest.as_ref().map(|l| l.version.clone());
        if let Some(version) = latest {
            self.save(|s| s.skipped = Some(version));
        }
    }

    pub fn unskip(&self) {
        self.save(|s| s.skipped = None);
    }

    fn save(&self, change: impl FnOnce(&mut Saved)) {
        {
            let mut inner = self.lock();
            change(&mut inner.saved);
            inner.saved.save();
        }
        self.refresh();
        self.notify();
    }

    /// The version skipped, while it's still ahead of this one.
    fn skipped(&self) -> Option<String> {
        self.lock().saved.skipped.clone().filter(|s| is_newer(s, &self.current))
    }

    /// The version Go back returns to: the one the last update replaced, when it's older than this one and its
    /// installer can still be had.
    pub fn previous(&self) -> Option<Release> {
        let inner = self.lock();
        let replaced = inner.saved.previous.as_deref()?;
        inner.releases.iter().find(|r| r.version == replaced && is_newer(&self.current, &r.version)).cloned()
    }

    /// Everything Settings → Updates shows, as the Mac app reports it (core/web/api.ts, UpdateReport).
    pub fn report(&self) -> Value {
        let previous = self.previous().map(|p| p.version);
        let skipped = self.skipped();
        let working = self.working();
        let inner = self.lock();
        let mut out = json!({
            "enabled": true,
            "current": self.current,
            "beta": inner.saved.beta,
            "working": working,
            "skipped": skipped,
            "previous": previous,
            "checked_at": inner.checked_at.map(iso_time),
        });
        let (state, version, extra): (&str, Option<&String>, Option<(&str, Value)>) = match &inner.state {
            State::Idle => ("idle", None, None),
            State::Checking => ("checking", None, None),
            State::UpToDate => ("up-to-date", None, None),
            State::Offline => ("offline", None, None),
            State::LockedDown => ("locked-down", None, None),
            State::Available(v) => ("available", Some(v), Some(("prerelease", json!(inner.latest.as_ref().map(|l| l.prerelease).unwrap_or(false))))),
            State::Downloading(v, p) => ("downloading", Some(v), Some(("progress", json!(p)))),
            State::Installing(v) => ("installing", Some(v), None),
            State::GoingBack(v) => ("going-back", Some(v), None),
            State::Failed(why) => ("failed", None, Some(("error", json!(why)))),
        };
        out["state"] = json!(state);
        if let Some(v) = version {
            out["version"] = json!(v);
        }
        if let Some((key, value)) = extra {
            out[key] = value;
        }
        out
    }

    // MARK: Installing

    /// Installs the version on offer.
    pub fn install(self: &Arc<Self>) {
        let latest = self.lock().latest.clone();
        if let Some(release) = latest {
            self.lock().last_try = Some(Attempt::Install);
            self.install_release(release, false);
        }
    }

    /// Returns to the version the last update replaced.
    pub fn go_back(self: &Arc<Self>) {
        self.lock().last_try = Some(Attempt::GoBack);
        match self.previous() {
            Some(release) => self.install_release(release, true),
            None => self.set_state(State::Failed(format!("There's no earlier version of {} to go back to.", config::NAME))),
        }
    }

    /// After a failure: whatever failed, again (or a fresh look).
    pub fn try_again(self: &Arc<Self>) {
        let (last, has_latest) = {
            let inner = self.lock();
            (inner.last_try, inner.latest.is_some())
        };
        match last {
            Some(Attempt::GoBack) => self.go_back(),
            Some(Attempt::Install) if has_latest => self.install(),
            _ => self.check_soon(true),
        }
    }

    fn install_release(self: &Arc<Self>, release: Release, going_back: bool) {
        if self.working() {
            return;
        }
        let doing = if going_back { "go back" } else { "update" };
        if lockdown_on() != Some(false) {
            self.set_state(State::Failed(format!("Lockdown is on, so {} didn't {doing}: that takes a download. Turn it off in Settings to go ahead.", config::NAME)));
            return;
        }
        if server_busy() {
            self.set_state(State::Failed(format!("{} is in the middle of something, so it didn't {doing}. Try again when it's done.", config::NAME)));
            return;
        }
        let Some(folder) = self.exe.parent().map(Path::to_path_buf) else { return };
        if !writable(&folder) {
            self.set_state(State::Failed(format!(
                "{} can't {doing} where it's installed ({}). Download the new version and install it instead.",
                config::NAME,
                folder.display()
            )));
            return;
        }
        self.set_state(if going_back { State::GoingBack(release.version.clone()) } else { State::Downloading(release.version.clone(), None) });
        let updater = self.clone();
        thread::spawn(move || match updater.download_and_hand_over(&release, &folder, going_back) {
            Ok(()) => {
                let quit = updater.quit.lock().unwrap_or_else(|e| e.into_inner()).clone();
                match quit {
                    Some(quit) => quit(),
                    None => std::process::exit(0),
                }
            }
            Err(why) => {
                log(&format!("couldn't {doing} to {}: {why}", release.version));
                updater.set_state(State::Failed(why));
            }
        });
    }

    #[cfg(windows)]
    fn download_and_hand_over(&self, release: &Release, folder: &Path, going_back: bool) -> Result<(), String> {
        let work = std::env::temp_dir().join(format!("{}-update-{}-{}", config::ID, std::process::id(), now()));
        fs::create_dir_all(&work).map_err(|e| format!("Couldn't make a folder for the download ({e})"))?;
        let installer = work.join(&release.name);
        log(&format!("downloading {} from {}", release.name, release.installer));
        let digest = self.download(release, &installer, going_back)?;
        let published = fetch_text(&release.checksum, &self.current)
            .and_then(|t| parse_checksum(&t))
            .ok_or("The update has no published checksum, so it wasn't installed")?;
        if digest != published {
            return Err("The update didn't match its published checksum, so it wasn't installed".into());
        }
        if !going_back {
            self.set_state(State::Installing(release.version.clone()));
        }
        check_installer(&installer, &release.name, &release.version)?;
        // Waits (up to a minute) for background work to finish: the install stops the server.
        let deadline = Instant::now() + Duration::from_secs(60);
        while server_busy() {
            if Instant::now() >= deadline {
                return Err(format!("{} is in the middle of something, so it didn't update. Try again when it's done.", config::NAME));
            }
            thread::sleep(Duration::from_secs(1));
        }

        // The installer replaces this program, so a copy of it, elsewhere, waits for the app to quit and runs it.
        let helper = work.join(format!("{}-updater.exe", config::ID));
        fs::copy(&self.exe, &helper).map_err(|e| format!("Couldn't get the update ready ({e})"))?;
        let mut command = Command::new(&helper);
        command
            .arg(APPLY_FLAG)
            .arg(&installer)
            .arg(std::process::id().to_string())
            .arg(&self.exe)
            .arg(&release.version)
            .arg(&self.current)
            .arg(if going_back { "back" } else { "forward" })
            .current_dir(&work)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW;
        // Out of the job the app's server is in, so it isn't ended along with the app (not every job allows it).
        let spawned = command.creation_flags(flags | CREATE_BREAKAWAY_FROM_JOB).spawn().or_else(|_| command.creation_flags(flags).spawn());
        spawned.map_err(|e| format!("Couldn't start installing the update ({e})"))?;
        log(&format!("handed {} over to the installer; quitting", release.version));
        let _ = folder;
        Ok(())
    }

    #[cfg(not(windows))]
    fn download_and_hand_over(&self, _release: &Release, _folder: &Path, _going_back: bool) -> Result<(), String> {
        Err("Updating itself isn't here yet on this system (PORTING.md, chunk 8).".into())
    }

    /// Downloads straight to disk, showing progress, and returns the file's SHA-256.
    #[cfg(windows)]
    fn download(&self, release: &Release, target: &Path, going_back: bool) -> Result<String, String> {
        let failed = |e: String| format!("Couldn't download the update ({e})");
        let mut response = minreq::get(&release.installer)
            .with_header("User-Agent", user_agent(&self.current))
            .with_header("Accept", "application/octet-stream")
            .with_timeout(3600)
            .send_lazy()
            .map_err(|e| failed(e.to_string()))?;
        if response.status_code != 200 {
            return Err(failed(format!("the server answered {}", response.status_code)));
        }
        let total: Option<u64> = response.headers.get("content-length").and_then(|v| v.trim().parse().ok());
        let mut file = File::create(target).map_err(|e| failed(e.to_string()))?;
        let mut hasher = Sha256::new();
        let mut buffer = vec![0u8; 1 << 16];
        let mut done: u64 = 0;
        let mut shown = Instant::now();
        loop {
            let n = response.read(&mut buffer).map_err(|e| failed(e.to_string()))?;
            if n == 0 {
                break;
            }
            file.write_all(&buffer[..n]).map_err(|e| failed(e.to_string()))?;
            hasher.update(&buffer[..n]);
            done += n as u64;
            if !going_back && shown.elapsed() >= Duration::from_millis(300) {
                shown = Instant::now();
                if let Some(total) = total.filter(|t| *t > 0) {
                    self.set_state(State::Downloading(release.version.clone(), Some((done as f64 / total as f64).min(1.0))));
                }
            }
        }
        file.flush().map_err(|e| failed(e.to_string()))?;
        if let Some(total) = total {
            if done != total {
                return Err(failed(format!("got {done} of {total} bytes")));
            }
        }
        Ok(hasher.finalize().iter().map(|b| format!("{b:02x}")).collect())
    }
}

// MARK: Looking

/// Where releases are looked up: <PREFIX>_UPDATE_URL (tests), else the recent releases of the repo in app.json.
/// The list rather than GitHub's "latest", which never includes pre-releases and might lack this platform.
fn feed() -> Option<String> {
    if let Some(url) = config::env("UPDATE_URL") {
        return Some(url);
    }
    (!config::UPDATE_REPO.is_empty()).then(|| format!("https://api.github.com/repos/{}/releases?per_page=30", config::UPDATE_REPO))
}

fn user_agent(current: &str) -> String {
    format!("{}/{current} ({})", config::NAME.replace(' ', ""), std::env::consts::OS)
}

fn fetch_json(url: &str, current: &str) -> Option<Value> {
    let response = minreq::get(url)
        .with_header("Accept", "application/vnd.github+json")
        .with_header("User-Agent", user_agent(current))
        .with_timeout(30)
        .send()
        .ok()?;
    if response.status_code != 200 {
        return None;
    }
    serde_json::from_str(response.as_str().ok()?).ok()
}

#[cfg(windows)]
fn fetch_text(url: &str, current: &str) -> Option<String> {
    let response = minreq::get(url).with_header("User-Agent", user_agent(current)).with_timeout(30).send().ok()?;
    (response.status_code == 200).then(|| response.as_str().ok().map(String::from)).flatten()
}

/// Lockdown (the family's rule 9: nothing leaves this computer): GET /api/lockdown. None when the server can't say,
/// which the callers treat as on, so no look or download goes out on a guess.
fn lockdown_on() -> Option<bool> {
    let response = minreq::get(format!("{}/api/lockdown", config::server_url())).with_timeout(3).send().ok()?;
    if response.status_code != 200 {
        return None;
    }
    lockdown_from(response.as_str().ok()?)
}

/// What GET /api/lockdown says: {"on": true, ...}. None for anything else.
pub fn lockdown_from(body: &str) -> Option<bool> {
    serde_json::from_str::<Value>(body).ok()?.get("on")?.as_bool()
}

/// The server's GET /api/jobs/busy. Only a clear yes counts: a server that doesn't answer has no work to lose.
fn server_busy() -> bool {
    minreq::get(format!("{}/api/jobs/busy", config::server_url()))
        .with_timeout(3)
        .send()
        .ok()
        .filter(|r| r.status_code == 200)
        .and_then(|r| serde_json::from_str::<Value>(r.as_str().ok()?).ok())
        .and_then(|v| v.get("busy").and_then(|b| b.as_bool()))
        .unwrap_or(false)
}

// MARK: Which release (the Mac's UpdateRules)

/// This computer's installer in a release: <Slug>-<version>-windows-<arch>.exe.
pub fn installer_name(version: &str) -> String {
    format!("{}-{version}-windows-{ARCH}.exe", config::NAME.replace(' ', ""))
}

/// A release from GitHub's JSON, if it isn't a draft and has this computer's installer for its own version with the
/// checksum beside it. Other assets (the fixed-name copy for a download page, the Mac's disk image) don't count.
pub fn release(json: &Value) -> Option<Release> {
    if json.get("draft").and_then(|d| d.as_bool()).unwrap_or(false) {
        return None;
    }
    let tag = json.get("tag_name")?.as_str()?;
    let version = tag.strip_prefix('v').unwrap_or(tag).to_string();
    let name = installer_name(&version);
    let asset = |wanted: &str| -> Option<String> {
        json.get("assets")?.as_array()?.iter().find_map(|a| {
            (a.get("name")?.as_str()? == wanted).then(|| a.get("browser_download_url")?.as_str().map(String::from)).flatten()
        })
    };
    let installer = asset(&name)?;
    let checksum = asset(&format!("{name}.sha256"))?;
    Some(Release {
        version,
        prerelease: json.get("prerelease").and_then(|p| p.as_bool()).unwrap_or(false),
        notes: json.get("html_url").and_then(|u| u.as_str()).map(String::from),
        name,
        installer,
        checksum,
    })
}

/// GitHub's answer as releases: a list, or a single release (a test feed).
pub fn releases(parsed: &Value) -> Vec<Release> {
    match parsed {
        Value::Array(items) => items.iter().filter_map(release).collect(),
        Value::Object(_) => release(parsed).into_iter().collect(),
        _ => Vec::new(),
    }
}

/// The release to offer, if any: the newest one newer than `current`, never the skipped version, and a pre-release
/// only with beta updates on.
pub fn offer(releases: &[Release], current: &str, beta: bool, skipped: Option<&str>) -> Option<Release> {
    releases
        .iter()
        .filter(|r| beta || !r.prerelease)
        .filter(|r| skipped.map(|s| !same(&r.version, s)).unwrap_or(true))
        .filter(|r| is_newer(&r.version, current))
        .fold(None, |best: Option<&Release>, r| match best {
            Some(b) if !is_newer(&r.version, &b.version) => Some(b),
            _ => Some(r),
        })
        .cloned()
}

/// Whether version a is higher than b, number by number ("0.10.0" > "0.9.1", "0.8.0-build.7" > "0.8.0"); a missing
/// number counts as 0, so "1.0" is the same as "1.0.0".
pub fn is_newer(a: &str, b: &str) -> bool {
    let numbers = |v: &str| -> Vec<u64> {
        v.trim_start_matches('v').split(['.', '-', '+']).filter_map(|p| p.parse::<u64>().ok()).collect()
    };
    let (x, y) = (numbers(a), numbers(b));
    for i in 0..x.len().max(y.len()) {
        let (p, q) = (x.get(i).copied().unwrap_or(0), y.get(i).copied().unwrap_or(0));
        if p != q {
            return p > q;
        }
    }
    false
}

pub fn same(a: &str, b: &str) -> bool {
    !is_newer(a, b) && !is_newer(b, a)
}

#[cfg_attr(not(windows), allow(dead_code))]
/// The first word of a .sha256 file ("<hex>  <name>"), if it's a SHA-256.
pub fn parse_checksum(text: &str) -> Option<String> {
    let word = text.split_whitespace().next()?.to_lowercase();
    (word.len() == 64 && word.chars().all(|c| c.is_ascii_hexdigit())).then_some(word)
}

// MARK: Bits

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// Seconds since 1970 as "2026-11-04T22:13:58Z".
pub fn iso_time(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let rest = secs % 86_400;
    // Howard Hinnant's days-to-civil.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z", rest / 3600, rest % 3600 / 60, rest % 60)
}

fn writable(folder: &Path) -> bool {
    let probe = folder.join(".update-check");
    match File::create(&probe) {
        Ok(_) => {
            let _ = fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

/// Is this the installer it should be? A Windows program (MZ), named as releases name it, whose version resource
/// (the installer build writes it) names this app at that version.
#[cfg(windows)]
fn check_installer(file: &Path, expected_name: &str, version: &str) -> Result<(), String> {
    let not_ours = |why: &str| format!("The update isn't {}'s installer ({why}), so it wasn't installed", config::NAME);
    if file.file_name().map(|n| n.to_string_lossy() != expected_name).unwrap_or(true) {
        return Err(not_ours("wrong name"));
    }
    let mut head = [0u8; 2];
    File::open(file).and_then(|mut f| f.read_exact(&mut head)).map_err(|e| not_ours(&e.to_string()))?;
    if &head != b"MZ" {
        return Err(not_ours("not a program"));
    }
    match os::version_string(file, "ProductName") {
        Some(name) if name == config::NAME => {}
        Some(name) => return Err(not_ours(&format!("it's {name}"))),
        None => return Err(not_ours("no product name")),
    }
    match os::version_string(file, "ProductVersion") {
        Some(v) if same(&v, version) => Ok(()),
        Some(v) => Err(not_ours(&format!("it's version {v}, not {version}"))),
        None => Err(not_ours("no version")),
    }
}

/// Downloads from earlier updates (each left its folder: the program that installed it ran from there).
fn clean_old_downloads() {
    let prefix = format!("{}-update-", config::ID);
    let Ok(entries) = fs::read_dir(std::env::temp_dir()) else { return };
    for entry in entries.flatten() {
        if entry.file_name().to_string_lossy().starts_with(&prefix) {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
}

/// Appends a line to logs/update.log in the data folder (started afresh when it gets big).
pub fn log(line: &str) {
    let path = config::data_dir().join("logs").join("update.log");
    if let Some(dir) = path.parent() {
        let _ = fs::create_dir_all(dir);
    }
    let big = fs::metadata(&path).map(|m| m.len() > 1 << 20).unwrap_or(false);
    let file = if big { File::create(&path) } else { OpenOptions::new().create(true).append(true).open(&path) };
    if let Ok(mut file) = file {
        let _ = writeln!(file, "{} {line}", iso_time(now()));
    }
}

// MARK: Installing it (a copy of this program, run with --apply-update)

/// `--apply-update <installer> <pid> <app exe> <version> <from version> <forward|back>`: waits for the app (pid) and
/// anything else running from its folder to end, runs the installer silently over it, remembers what Go back
/// returns to, and opens the new version (unless <PREFIX>_UPDATE_NO_RELAUNCH, for tests).
#[cfg(windows)]
pub fn apply(args: &[String]) -> i32 {
    let rest: Vec<&String> = args.iter().skip_while(|a| a.as_str() != APPLY_FLAG).skip(1).collect();
    if rest.len() < 6 {
        log("--apply-update needs <installer> <pid> <exe> <version> <from> <forward|back>");
        return 2;
    }
    let installer = PathBuf::from(rest[0]);
    let pid: u32 = rest[1].parse().unwrap_or(0);
    let exe = PathBuf::from(rest[2]);
    let Some(folder) = exe.parent().map(Path::to_path_buf) else { return 2 };
    let (version, from, going_back) = (rest[3].as_str(), rest[4].as_str(), rest[5] == "back");
    log(&format!("installing {version} over {from} in {}", folder.display()));

    if pid != 0 && !os::wait_for_exit(pid, Duration::from_secs(90)) {
        log("the app didn't quit in time; installing anyway");
    }
    // The server (Python) ends with the app; anything still running from the folder would keep files locked.
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        let left = os::processes_in(&folder);
        if left.is_empty() {
            break;
        }
        if Instant::now() >= deadline {
            log(&format!("ending {} program(s) still running from the install", left.len()));
            for pid in left {
                os::terminate(pid);
            }
            thread::sleep(Duration::from_secs(1));
            break;
        }
        thread::sleep(Duration::from_millis(250));
    }

    // NSIS: /S silent, /UPDATE keeps your shortcuts as they are; /D= (last, unquoted) installs over this folder.
    let status = Command::new(&installer)
        .arg("/S")
        .arg("/UPDATE")
        .raw_arg(format!("/D={}", folder.display()))
        .creation_flags(CREATE_NO_WINDOW)
        .status();
    let outcome = match status {
        Ok(s) if s.success() => Ok(()),
        Ok(s) => Err(format!("The installer for {version} stopped with code {}", s.code().unwrap_or(-1))),
        Err(e) => Err(format!("Couldn't run the installer for {version} ({e})")),
    };
    let mut saved = Saved::load();
    match &outcome {
        Ok(()) if going_back => {
            saved.skipped = Some(from.to_string()); // don't offer the version you left; a newer one, yes
            saved.previous = None;
        }
        Ok(()) => saved.previous = Some(from.to_string()),
        Err(why) => saved.last_error = Some(why.clone()),
    }
    saved.save();
    let _ = fs::remove_file(&installer);
    match &outcome {
        Ok(()) => log(&format!("installed {version}")),
        Err(why) => log(&format!("couldn't install {version}: {why}")),
    }

    if config::env("UPDATE_NO_RELAUNCH").is_none() {
        let opened = Command::new(&exe)
            .current_dir(&folder)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
            .spawn();
        if let Err(e) = opened {
            log(&format!("couldn't open {} ({e})", exe.display()));
        }
    }
    i32::from(outcome.is_err())
}

#[cfg(not(windows))]
pub fn apply(_args: &[String]) -> i32 {
    log("--apply-update isn't here yet on this system");
    2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lockdown_counts_only_a_clear_answer() {
        assert_eq!(lockdown_from(r#"{"on": true, "parked": 2}"#), Some(true));
        assert_eq!(lockdown_from(r#"{"on": false, "parked": 0}"#), Some(false));
        assert_eq!(lockdown_from(r#"{"lockdown": true}"#), None);
        assert_eq!(lockdown_from("<html>"), None);
    }

    fn rel(version: &str, prerelease: bool, files: &[&str]) -> Value {
        let assets: Vec<Value> = files.iter().map(|f| json!({"name": f, "browser_download_url": format!("http://127.0.0.1:1/{f}")})).collect();
        json!({"tag_name": format!("v{version}"), "prerelease": prerelease, "draft": false, "html_url": "http://x/", "assets": assets})
    }

    fn windows(version: &str, prerelease: bool) -> Value {
        let name = installer_name(version);
        let checksum = format!("{name}.sha256");
        rel(version, prerelease, &[name.as_str(), checksum.as_str()])
    }

    #[test]
    fn versions_compare_by_their_numbers() {
        assert!(is_newer("0.10.0", "0.9.1"));
        assert!(is_newer("0.8.0-build.7", "0.8.0"));
        assert!(is_newer("0.8.0-build.7", "0.8.0-build.6"));
        assert!(is_newer("0.8.1", "0.8.0-build.900"));
        assert!(is_newer("0.7.1-build.2", "0.0.1"));
        assert!(!is_newer("1.0", "1.0.0") && same("1.0", "v1.0.0"));
    }

    #[test]
    fn a_release_needs_this_computers_installer_and_its_checksum() {
        let r = release(&windows("0.8.0", false)).unwrap();
        assert_eq!(r.version, "0.8.0");
        assert!(r.checksum.ends_with(".sha256"));
        let name = installer_name("0.8.0");
        assert!(release(&rel("0.8.0", false, &[name.as_str()])).is_none(), "no checksum: passed over");
        let fixed = format!("{}-windows-{ARCH}.exe", config::NAME.replace(' ', ""));
        assert!(release(&rel("0.8.0", false, &[fixed.as_str(), "X-0.8.0-arm64.dmg"])).is_none(), "the download page's copy doesn't count");
        let mut draft = windows("0.9.0", false);
        draft["draft"] = json!(true);
        assert!(release(&draft).is_none());
    }

    #[test]
    fn the_newest_is_offered_betas_only_when_asked_and_never_the_skipped_one() {
        let list = releases(&json!([windows("0.10.0", true), windows("0.9.0", false), windows("0.8.0", false)]));
        assert_eq!(offer(&list, "0.8.0", false, None).unwrap().version, "0.9.0");
        assert_eq!(offer(&list, "0.8.0", true, None).unwrap().version, "0.10.0");
        assert_eq!(offer(&list, "0.8.0", false, Some("0.9.0")), None);
        assert_eq!(offer(&list, "0.10.0", true, None), None);
        assert_eq!(releases(&windows("0.9.0", false)).len(), 1, "a single release, as a test feed gives");
    }

    #[test]
    fn checksums_and_times_read_as_expected() {
        let sum = "a".repeat(64);
        assert_eq!(parse_checksum(&format!("{}  App-1.0.0-windows-x64.exe\n", sum.to_uppercase())), Some(sum));
        assert_eq!(parse_checksum("nope"), None);
        assert_eq!(iso_time(0), "1970-01-01T00:00:00Z");
        assert_eq!(iso_time(1_793_829_238), "2026-11-04T21:53:58Z");
        assert_eq!(iso_time(951_782_400), "2000-02-29T00:00:00Z");
    }
}
