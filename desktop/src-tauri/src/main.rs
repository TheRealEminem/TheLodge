//! The family's desktop app for Windows and Linux: the app's web app in its own window, a tray icon, and the app's
//! server (with its own Python) started and watched over by this process. The same shape as the Mac menu bar app
//! (mac/Sources/AppHost), with the same server and the same web app; app.json says which app it is (build.rs).

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod config;
mod login;
#[cfg_attr(windows, path = "os/windows.rs")]
#[cfg_attr(unix, path = "os/unix.rs")]
mod os;
mod selftest;
mod server;
mod update;
mod window;

use tauri::{Manager, RunEvent};

enum Mode {
    Normal { at_login: bool },
    About,
    WindowTest(Vec<String>),
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    // A copy of this program installing an update over the app (update.rs): no window, no tray.
    if args.iter().any(|a| a == update::APPLY_FLAG) {
        std::process::exit(update::apply(&args));
    }
    #[cfg(target_os = "linux")]
    os::before_window();
    let context: tauri::Context<tauri::Wry> = tauri::generate_context!();
    if args.iter().any(|a| a == "--version") {
        println!("{}", context.package_info().version);
        return;
    }
    let mode = if args.iter().any(|a| a == "--about") {
        Mode::About
    } else if args.iter().any(|a| a == "--window-test") {
        Mode::WindowTest(args.clone())
    } else {
        Mode::Normal { at_login: args.iter().any(|a| a == login::FLAG) }
    };

    let mut builder = tauri::Builder::default()
        // Without its link script: that script takes every target=_blank click and asks for the link over Tauri's
        // IPC, which the window isn't allowed (capabilities/default.json). The window opens them instead.
        .plugin(tauri_plugin_opener::Builder::new().open_js_links_on_click(false).build())
        .register_uri_scheme_protocol("shell", |ctx, request| window::bridge(ctx.app_handle(), request));
    if matches!(mode, Mode::Normal { .. }) {
        // Opening the app again (the Start menu, a second click) shows the window of the one already running.
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let app = app.clone();
            std::thread::spawn(move || app::open(&app, None));
        }));
    }
    let built = builder
        .setup(move |app| {
            let handle = app.handle().clone();
            match mode {
                Mode::Normal { at_login } => app::launch(&handle, at_login)?,
                Mode::About => {
                    println!("{}", serde_json::to_string_pretty(&selftest::about(&handle)).unwrap_or_default());
                    std::process::exit(0);
                }
                Mode::WindowTest(args) => selftest::window_test(handle, args),
            }
            Ok(())
        })
        .build(context)
        .expect("error while building the app");

    built.run(|app, event| match event {
        // The window closing (or being hidden) isn't the end: the app lives in the tray until Quit.
        RunEvent::ExitRequested { code: None, api, .. } => api.prevent_exit(),
        RunEvent::Exit => {
            if let Some(state) = app.try_state::<app::AppState>() {
                if let Some(server) = &state.server {
                    server.stop();
                }
            }
        }
        _ => {}
    });
}
