//! Open at login (SMAppService on the Mac). The app starts with --at-login: the tray icon and the server, no window.
//!
//! - Windows: a value named after the app under HKCU\Software\Microsoft\Windows\CurrentVersion\Run.
//! - Linux: ~/.config/autostart/<id>.desktop ($XDG_CONFIG_HOME), the freedesktop entry GNOME, KDE and the rest
//!   read. For an AppImage it's the AppImage file that's started (the program inside lives in a temporary mount).
//! - A development run on a Mac: not offered (the Mac app is mac/).

use std::path::Path;

pub const FLAG: &str = "--at-login";

/// Whether open at login can be offered here.
pub fn available() -> bool {
    cfg!(any(windows, target_os = "linux"))
}

#[cfg(windows)]
mod imp {
    use super::FLAG;
    use crate::config;
    use crate::os;
    use std::path::Path;

    const RUN: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
    /// Where Task Manager's Startup apps tab keeps the ones you turned off.
    const APPROVED: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run";

    fn command(exe: &Path) -> String {
        format!("\"{}\" {FLAG}", exe.display())
    }

    /// On if Windows will start this program at login: the Run value points here and it isn't turned off in Task
    /// Manager (StartupApproved: an odd first byte means off).
    pub fn enabled(exe: &Path) -> bool {
        let Some(value) = os::reg_get_string(RUN, config::NAME) else { return false };
        if !points_at(&value, exe) {
            return false;
        }
        match os::reg_get_binary(APPROVED, config::NAME) {
            Some(bytes) => bytes.first().map(|b| b & 1 == 0).unwrap_or(true),
            None => true,
        }
    }

    pub fn set(exe: &Path, on: bool) -> bool {
        // Task Manager's "off" would outlast turning it on here; forget it either way.
        os::reg_delete(APPROVED, config::NAME);
        if on {
            os::reg_set_string(RUN, config::NAME, &command(exe))
        } else {
            os::reg_delete(RUN, config::NAME)
        }
    }

    /// The Run value starts this program (it's "\"C:\\...\\App.exe\" --at-login", or just a path).
    pub(super) fn points_at(value: &str, exe: &Path) -> bool {
        let value = value.trim();
        let path = match value.strip_prefix('"') {
            Some(rest) => rest.split('"').next().unwrap_or(""),
            None => value.split(" --").next().unwrap_or(value),
        };
        path.trim().eq_ignore_ascii_case(&exe.to_string_lossy())
    }
}

#[cfg(target_os = "linux")]
mod imp {
    use super::FLAG;
    use crate::config;
    use std::path::{Path, PathBuf};

    fn entry_path() -> PathBuf {
        config::xdg_dir("XDG_CONFIG_HOME", ".config").join("autostart").join(format!("{}.desktop", config::ID))
    }

    /// What to start: the AppImage, when this is one, else this program.
    fn target(exe: &Path) -> PathBuf {
        match std::env::var_os("APPIMAGE").map(PathBuf::from) {
            Some(appimage) if appimage.is_file() => appimage,
            _ => exe.to_path_buf(),
        }
    }

    /// A path as a desktop entry's Exec wants it: in double quotes, with ", `, $ and \ escaped (and the
    /// backslashes escaped again, as every string in the file is).
    pub(super) fn quoted(path: &Path) -> String {
        let mut out = String::from("\"");
        for c in path.to_string_lossy().chars() {
            match c {
                '"' | '`' | '$' => {
                    out.push_str("\\\\");
                    out.push(c);
                }
                '\\' => out.push_str("\\\\\\\\"),
                _ => out.push(c),
            }
        }
        out.push('"');
        out
    }

    pub(super) fn entry(exe: &Path) -> String {
        format!(
            "[Desktop Entry]\nType=Application\nName={name}\nExec={} {FLAG}\nIcon={id}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n",
            quoted(&target(exe)),
            name = config::NAME,
            id = config::ID,
        )
    }

    /// On if the autostart entry starts this app and isn't turned off (Hidden, or GNOME's own switch).
    pub fn enabled(exe: &Path) -> bool {
        let Ok(text) = std::fs::read_to_string(entry_path()) else { return false };
        let mut exec_ok = false;
        for line in text.lines().map(str::trim) {
            if let Some(exec) = line.strip_prefix("Exec=") {
                exec_ok = exec.starts_with(&quoted(&target(exe))) || exec.starts_with(&*target(exe).to_string_lossy());
            } else if line.eq_ignore_ascii_case("Hidden=true") || line.eq_ignore_ascii_case("X-GNOME-Autostart-enabled=false") {
                return false;
            }
        }
        exec_ok
    }

    pub fn set(exe: &Path, on: bool) -> bool {
        let path = entry_path();
        if on {
            if let Some(dir) = path.parent() {
                let _ = std::fs::create_dir_all(dir);
            }
            std::fs::write(&path, entry(exe)).is_ok()
        } else {
            match std::fs::remove_file(&path) {
                Ok(()) => true,
                Err(e) => e.kind() == std::io::ErrorKind::NotFound,
            }
        }
    }
}

#[cfg(target_os = "macos")]
mod imp {
    use std::path::Path;

    pub fn enabled(_exe: &Path) -> bool {
        false
    }

    pub fn set(_exe: &Path, _on: bool) -> bool {
        false
    }
}

pub fn enabled(exe: &Path) -> bool {
    imp::enabled(exe)
}

pub fn set(exe: &Path, on: bool) -> bool {
    imp::set(exe, on)
}

#[cfg(test)]
mod tests {
    #[cfg(windows)]
    #[test]
    fn the_run_value_names_this_program() {
        use std::path::PathBuf;
        let exe = PathBuf::from("C:\\Users\\Sam Lee\\AppData\\Local\\App\\App.exe");
        assert!(super::imp::points_at("\"C:\\Users\\Sam Lee\\AppData\\Local\\App\\App.exe\" --at-login", &exe));
        assert!(super::imp::points_at("\"c:\\users\\sam lee\\appdata\\local\\app\\app.exe\"", &exe));
        assert!(!super::imp::points_at("\"C:\\Elsewhere\\App.exe\" --at-login", &exe));
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn the_entry_starts_this_program() {
        use std::path::{Path, PathBuf};
        let exe = PathBuf::from("/home/sam lee/Apps/App.AppImage");
        assert_eq!(super::imp::quoted(&exe), "\"/home/sam lee/Apps/App.AppImage\"");
        assert_eq!(super::imp::quoted(Path::new("/a$b")), "\"/a\\\\$b\"");
        assert!(super::imp::entry(&exe).starts_with("[Desktop Entry]\nType=Application\n"));
    }
}
