//! Who this app is (AppConfig.swift on the Mac), baked in from app.json by build.rs, and where it keeps things.
//! Anything can be overridden from the environment as <envPrefix>_<KEY>, as on the Mac: <PREFIX>_DATA_DIR,
//! <PREFIX>_SERVER_URL (the window shows another server: development, or a server install), <PREFIX>_NO_OPEN
//! (tests: say what would open instead of opening it).

use std::path::PathBuf;

pub const NAME: &str = env!("FAMILY_APP_NAME");
pub const ID: &str = env!("FAMILY_APP_ID");
pub const PREFIX: &str = env!("FAMILY_APP_PREFIX");
/// GitHub "owner/repo" the updates come from; empty for none.
#[allow(dead_code)] // the updater (PORTING.md, chunk 6)
pub const UPDATE_REPO: &str = env!("FAMILY_UPDATE_REPO");

pub fn port() -> u16 {
    env("PORT").and_then(|p| p.parse().ok()).unwrap_or_else(|| env!("FAMILY_APP_PORT").parse().unwrap_or(8790))
}

/// <PREFIX>_<key> from the environment, if it's set and not empty.
pub fn env(key: &str) -> Option<String> {
    std::env::var(format!("{PREFIX}_{key}")).ok().filter(|v| !v.trim().is_empty())
}

/// Where the window points: the bundled server on this computer, unless <PREFIX>_SERVER_URL says otherwise.
pub fn server_url() -> String {
    env("SERVER_URL").map(|u| u.trim_end_matches('/').to_string()).unwrap_or_else(|| format!("http://127.0.0.1:{}", port()))
}

/// Everything the app keeps. Survives updating or uninstalling it (the installer never removes it).
/// %LOCALAPPDATA%\<Name>\data on Windows, $XDG_DATA_HOME/<Name> (~/.local/share/<Name>) on Linux.
/// core/server/family.py looks for the family folder beside it, so keep the two in step.
pub fn data_dir() -> PathBuf {
    if let Some(dir) = env("DATA_DIR") {
        return PathBuf::from(dir);
    }
    os_data_dir()
}

#[cfg(windows)]
fn os_data_dir() -> PathBuf {
    let local = std::env::var_os("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(|| home().join("AppData").join("Local"));
    local.join(NAME).join("data")
}

#[cfg(target_os = "linux")]
fn os_data_dir() -> PathBuf {
    xdg_dir("XDG_DATA_HOME", ".local/share").join(NAME)
}

/// A development run on a Mac (the Mac's own app is mac/, not this): beside the Mac app's data, never in it.
#[cfg(target_os = "macos")]
fn os_data_dir() -> PathBuf {
    home().join("Library").join("Application Support").join(format!("{NAME} (desktop shell)"))
}

pub fn log_file() -> PathBuf {
    data_dir().join("logs").join("server.log")
}

pub fn home() -> PathBuf {
    let var = if cfg!(windows) { "USERPROFILE" } else { "HOME" };
    std::env::var_os(var).map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."))
}

/// $XDG_<name> (XDG_DATA_HOME, XDG_CONFIG_HOME) when it's an absolute path, else that folder under home.
#[cfg(target_os = "linux")]
pub fn xdg_dir(var: &str, default: &str) -> PathBuf {
    match std::env::var_os(var).map(PathBuf::from).filter(|p| p.is_absolute()) {
        Some(dir) => dir,
        None => home().join(default),
    }
}

/// True when *this* app's server answers at `base` (not another family app that happens to use the port).
pub fn answering(base: &str) -> bool {
    let Ok(response) = minreq::get(format!("{base}/api/app")).with_timeout(2).send() else { return false };
    if response.status_code != 200 {
        return false;
    }
    let Ok(text) = response.as_str() else { return false };
    serde_json::from_str::<serde_json::Value>(text).ok().and_then(|v| v.get("id").and_then(|id| id.as_str()).map(|id| id == ID)).unwrap_or(false)
}
