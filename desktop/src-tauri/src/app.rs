//! The app (HostApp.swift on the Mac): starts the server (or finds it running), shows the window once it answers,
//! and lives in the tray until Quit. The tray menu is the Mac's menu bar menu.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::image::Image;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, Wry};
use tauri_plugin_opener::OpenerExt;

use crate::config;
use crate::login;
use crate::server::{self, Bundled, Server};
use crate::update::{State as UpdateState, Updater};
use crate::window;

/// How long the server may take to answer after starting (a slow disk on the first run can take a while).
const START_TIMEOUT: Duration = Duration::from_secs(40);

pub struct AppState {
    pub server: Option<Arc<Server>>,
    pub updater: Option<Arc<Updater>>,
    ready: AtomicBool,
    tray: Mutex<Option<TrayItems>>,
}

/// The menu items that change while the app runs.
struct TrayItems {
    menu: Menu<Wry>,
    status: MenuItem<Wry>,
    status_shown: bool,
    login: Option<CheckMenuItem<Wry>>,
    update: Option<MenuItem<Wry>>,
    beta: Option<CheckMenuItem<Wry>>,
}

/// Sets everything up: the server (if this build has one), the hidden window and the tray; then starts the server
/// and opens the window once it answers. Opened at login, only the server starts and the window waits for a click.
pub fn launch(app: &AppHandle, at_login: bool) -> tauri::Result<()> {
    let _ = std::fs::create_dir_all(config::data_dir());
    let resources = app.path().resource_dir().unwrap_or_default();
    let exe = std::env::current_exe().unwrap_or_default();
    let bundled = Bundled::locate(&resources);
    let updater = (bundled.is_some() && Updater::enabled_for(&exe)).then(|| Updater::new(app.package_info().version.to_string(), exe));
    let can = if updater.is_some() { format!("{},updates", server::CAN) } else { server::CAN.to_string() };
    let server = bundled.map(|b| Server::new(b, can));
    app.manage(AppState { server, updater: updater.clone(), ready: AtomicBool::new(false), tray: Mutex::new(None) });
    window::create(app)?;
    build_tray(app)?;
    if let Some(updater) = updater {
        let handle = app.clone();
        updater.set_quit(move || quit(&handle));
        let handle = app.clone();
        updater.observe(move || {
            refresh_updates(&handle);
            window::send_updates(&handle);
        });
        updater.begin();
    }
    let handle = app.clone();
    thread::spawn(move || begin(&handle, !at_login));
    Ok(())
}

fn no_open() -> bool {
    config::env("NO_OPEN").is_some()
}

/// Starts the server unless it already answers (another copy of the app may have it), waits for it, then shows
/// the window and keeps an eye on the server.
fn begin(app: &AppHandle, open_window: bool) {
    let state = app.state::<AppState>();
    let base = config::server_url();
    if open_window && !no_open() {
        window::show_loading(app);
    }
    if let Some(server) = &state.server {
        if !config::answering(&base) {
            if let Err(problem) = server.start(config::port()) {
                failed(app, &problem, open_window);
                return;
            }
        }
    }
    if !wait_for_server(app, &base) {
        let problem = state
            .server
            .as_ref()
            .and_then(|s| s.failure())
            .unwrap_or_else(|| format!("The server didn't start. Log: {}", config::log_file().display()));
        failed(app, &problem, open_window);
        return;
    }
    set_ready(app, true, None);
    if open_window {
        open(app, None);
    }
    watch(app);
}

fn wait_for_server(app: &AppHandle, base: &str) -> bool {
    let state = app.state::<AppState>();
    let deadline = Instant::now() + START_TIMEOUT;
    while Instant::now() < deadline {
        if config::answering(base) {
            return true;
        }
        if state.server.as_ref().and_then(|s| s.failure()).is_some() {
            return false;
        }
        thread::sleep(Duration::from_millis(250));
    }
    config::answering(base)
}

fn failed(app: &AppHandle, problem: &str, window_open: bool) {
    eprintln!("{} couldn't start: {problem}", config::NAME);
    set_ready(app, false, Some(problem));
    if window_open && !no_open() {
        window::loading_failed(app, problem);
    }
}

/// A second copy of the app uses the first one's server rather than fighting it for the port, and that server
/// stops when the first copy quits. So when nothing answers any more, start this copy's own server and reload.
fn watch(app: &AppHandle) {
    let state = app.state::<AppState>();
    let Some(server) = state.server.clone() else { return };
    let base = config::server_url();
    loop {
        thread::sleep(Duration::from_secs(3));
        if server.is_running() || server.is_stopping() || server.failure().is_some() || config::answering(&base) {
            continue;
        }
        if server.start(config::port()).is_err() {
            continue;
        }
        if wait_for_server(app, &base) {
            set_ready(app, true, None);
            window::reload(app);
        } else {
            set_ready(app, false, server.failure().as_deref());
        }
    }
}

/// Shows the window at a page ("settings"), or the loading page while the server isn't answering yet.
pub fn open(app: &AppHandle, page: Option<&str>) {
    let base = config::server_url();
    let target = match page {
        Some(page) => format!("{base}/#/{page}"),
        None => format!("{base}/"),
    };
    if no_open() {
        eprintln!("Would open {target}"); // tests: say what would open instead of opening it
        return;
    }
    if app.state::<AppState>().ready.load(Ordering::SeqCst) {
        window::show(app, &target);
    } else {
        window::show_loading(app);
    }
}

/// Stops the server and exits.
pub fn quit(app: &AppHandle) {
    let app = app.clone();
    thread::spawn(move || {
        if let Some(server) = &app.state::<AppState>().server {
            server.stop();
        }
        app.exit(0);
    });
}

// MARK: The tray

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let exe = std::env::current_exe().unwrap_or_default();
    let open_item = MenuItem::with_id(app, "open", format!("Open {}", config::NAME), true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
    let status = MenuItem::with_id(app, "status", "Starting…", false, None::<&str>)?;
    let login = if login::available() {
        Some(CheckMenuItem::with_id(app, "login", "Open at login", true, login::enabled(&exe), None::<&str>)?)
    } else {
        None
    };
    let has_updater = app.state::<AppState>().updater.is_some();
    let update = if has_updater { Some(MenuItem::with_id(app, "update", "Check for updates…", true, None::<&str>)?) } else { None };
    let beta = match &app.state::<AppState>().updater {
        Some(u) => Some(CheckMenuItem::with_id(app, "beta", "Beta updates", true, u.beta(), None::<&str>)?),
        None => None,
    };
    let data = MenuItem::with_id(app, "data", "Show data folder", true, None::<&str>)?;
    let log = MenuItem::with_id(app, "log", "Show server log", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", format!("Quit {}", config::NAME), true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_item, &settings, &status, &PredefinedMenuItem::separator(app)?])?;
    if let (Some(update), Some(beta)) = (&update, &beta) {
        menu.append_items(&[update, beta])?;
    }
    if let Some(login) = &login {
        menu.append(login)?;
    }
    if update.is_some() || login.is_some() {
        menu.append(&PredefinedMenuItem::separator(app)?)?;
    }
    menu.append_items(&[&data, &log, &PredefinedMenuItem::separator(app)?, &quit_item])?;

    TrayIconBuilder::with_id("main")
        .icon(Image::from_bytes(include_bytes!("../../../identity/desktop/32x32.png"))?)
        .tooltip(config::NAME)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| on_menu(app, event.id().0.as_str()))
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                let app = tray.app_handle().clone();
                thread::spawn(move || open(&app, None));
            }
        })
        .build(app)?;
    *app.state::<AppState>().tray.lock().unwrap_or_else(|e| e.into_inner()) =
        Some(TrayItems { menu, status, status_shown: true, login, update, beta });
    Ok(())
}

/// The menu says "Starting…" or what went wrong, and nothing once the server answers (as on the Mac).
fn set_ready(app: &AppHandle, ready: bool, problem: Option<&str>) {
    let state = app.state::<AppState>();
    state.ready.store(ready, Ordering::SeqCst);
    let mut tray = state.tray.lock().unwrap_or_else(|e| e.into_inner());
    let Some(items) = tray.as_mut() else { return };
    if ready {
        if items.status_shown && items.menu.remove(&items.status).is_ok() {
            items.status_shown = false;
        }
        return;
    }
    let text: String = problem.unwrap_or("Starting…").chars().take(160).collect();
    let _ = items.status.set_text(text);
    if !items.status_shown && items.menu.insert(&items.status, 2).is_ok() {
        items.status_shown = true;
    }
}

fn on_menu(app: &AppHandle, id: &str) {
    match id {
        "open" => {
            let app = app.clone();
            thread::spawn(move || open(&app, None));
        }
        "settings" => {
            let app = app.clone();
            thread::spawn(move || open(&app, Some("settings")));
        }
        "login" => {
            let exe = std::env::current_exe().unwrap_or_default();
            let want = !login::enabled(&exe);
            login::set(&exe, want);
            let state = app.state::<AppState>();
            let tray = state.tray.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(item) = tray.as_ref().and_then(|t| t.login.as_ref()) {
                let _ = item.set_checked(login::enabled(&exe));
            }
        }
        "data" => {
            let _ = app.opener().open_path(config::data_dir().to_string_lossy(), None::<&str>);
        }
        "log" => {
            let log = config::log_file();
            let _ = app.opener().open_path(log.to_string_lossy(), None::<&str>);
        }
        "update" => {
            let Some(updater) = app.state::<AppState>().updater.clone() else { return };
            thread::spawn(move || match updater.state() {
                UpdateState::Available(_) => updater.install(),
                UpdateState::Failed(_) => updater.try_again(),
                _ => updater.check(true),
            });
        }
        "beta" => {
            if let Some(updater) = app.state::<AppState>().updater.clone() {
                let on = !updater.beta();
                thread::spawn(move || updater.set_beta(on));
            }
        }
        "quit" => quit(app),
        _ => {}
    }
}

/// The tray's update line, as the Mac menu words it: what's on offer, how it's going, or what went wrong.
fn update_line(state: &UpdateState) -> (String, bool) {
    match state {
        UpdateState::Idle => ("Check for updates…".into(), true),
        UpdateState::Checking => ("Checking for updates…".into(), false),
        UpdateState::UpToDate => ("Up to date · Check again".into(), true),
        UpdateState::Offline => ("Couldn't reach GitHub · Try again".into(), true),
        UpdateState::LockedDown => ("Lockdown is on: no update checks".into(), false),
        UpdateState::Available(v) => (format!("Install version {v}…"), true),
        UpdateState::Downloading(v, p) => (format!("Downloading {v}…{}", p.map(|p| format!(" {:.0}%", p * 100.0)).unwrap_or_default()), false),
        UpdateState::Installing(v) => (format!("Installing {v}…"), false),
        UpdateState::GoingBack(v) => (format!("Going back to {v}…"), false),
        UpdateState::Failed(why) => (format!("{} · Try again", why.chars().take(120).collect::<String>()), true),
    }
}

fn refresh_updates(app: &AppHandle) {
    let state = app.state::<AppState>();
    let Some(updater) = state.updater.clone() else { return };
    let tray = state.tray.lock().unwrap_or_else(|e| e.into_inner());
    let Some(items) = tray.as_ref() else { return };
    if let Some(item) = &items.update {
        let (text, enabled) = update_line(&updater.state());
        let _ = item.set_text(text);
        let _ = item.set_enabled(enabled && !updater.working());
    }
    if let Some(beta) = &items.beta {
        let _ = beta.set_checked(updater.beta());
    }
}

/// Settings → Updates in the window (window.rs passes on its "updates:<what>"), as on the Mac. Going back asks first.
pub fn updates_command(app: &AppHandle, what: &str) {
    let Some(updater) = app.state::<AppState>().updater.clone() else {
        window::send_updates(app);
        return;
    };
    let (handle, what) = (app.clone(), what.to_string());
    thread::spawn(move || {
        match what.as_str() {
            "check" => updater.check(true),
            "install" => updater.install(),
            "skip" => updater.skip(),
            "unskip" => updater.unskip(),
            "beta-on" => updater.set_beta(true),
            "beta-off" => updater.set_beta(false),
            "try-again" => updater.try_again(),
            "go-back" => {
                if let Some(previous) = updater.previous() {
                    if confirm_go_back(&previous.version, &updater) {
                        updater.go_back();
                    }
                }
            }
            _ => {}
        }
        window::send_updates(&handle);
    });
}

/// Going back replaces the app and restarts it, so it asks first (the Mac's alert, in Windows' own words box).
fn confirm_go_back(previous: &str, updater: &Updater) -> bool {
    let current = updater.report().get("current").and_then(|c| c.as_str()).unwrap_or_default().to_string();
    let name = config::NAME;
    let text = format!(
        "{name} {current} is replaced with {previous}, the version it updated from, and restarts. Your data stays. \
         {current} won't be offered again; the next version will."
    );
    #[cfg(windows)]
    return crate::os::ask(&format!("Go back to {name} {previous}?"), &text);
    #[cfg(not(windows))]
    {
        let _ = text;
        true
    }
}
