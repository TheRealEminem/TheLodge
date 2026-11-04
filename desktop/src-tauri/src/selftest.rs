//! Checks that drive the real installed program and its real window, for CI (the smoke tests) and for looking at
//! a real machine. Unit tests and a browser miss what only the installed app on another system shows.
//!
//!   --version                            the version, and nothing else
//!   --about                              who this app is and where it looks for things, as JSON
//!   --window-test <url> <out.png> [s]    opens the window at <url>, waits (up to s seconds, 20 by default) for the
//!                                        web app to name itself in the title, and saves a picture of the window.
//!                                        Exits 0 only if both happened.

use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

use crate::config;
use crate::server::Bundled;
use crate::window;

/// The arguments after `flag`.
fn args_after<'a>(args: &'a [String], flag: &str) -> Vec<&'a String> {
    args.iter().skip_while(|a| a.as_str() != flag).skip(1).collect()
}

/// Who this app is and where it looks, from inside the installed program (so a test sees the real paths).
pub fn about(app: &AppHandle) -> serde_json::Value {
    let resources = app.path().resource_dir().unwrap_or_default();
    serde_json::json!({
        "name": config::NAME,
        "id": config::ID,
        "prefix": config::PREFIX,
        "port": config::port(),
        "version": app.package_info().version.to_string(),
        "update_repo": config::UPDATE_REPO,
        "server_url": config::server_url(),
        "data_dir": config::data_dir(),
        "resources": resources,
        "bundled": Bundled::locate(&resources).is_some(),
        "os": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
    })
}

pub fn window_test(app: AppHandle, args: Vec<String>) {
    let rest = args_after(&args, "--window-test");
    if rest.len() < 2 {
        println!("usage: --window-test <url> <out.png> [seconds]");
        std::process::exit(2);
    }
    let url = rest[0].clone();
    let out = rest[1].clone();
    let wait = rest.get(2).and_then(|s| s.parse::<f64>().ok()).unwrap_or(20.0);
    if cfg!(not(windows)) {
        println!("--window-test isn't here yet on this system (PORTING.md, chunk 8)");
        std::process::exit(3);
    }
    if let Err(e) = window::create(&app) {
        println!("couldn't make the window: {e}");
        std::process::exit(1);
    }
    window::catch_links();
    thread::spawn(move || {
        window::show(&app, &url);
        let Some(win) = app.get_webview_window(window::LABEL) else {
            println!("no window");
            std::process::exit(1);
        };
        // The web app sets the page's title to the app's name once the server has answered (core/web/App.tsx).
        let expected = serde_json::to_string(config::NAME).unwrap_or_default();
        let deadline = Instant::now() + Duration::from_secs_f64(wait);
        let mut title = String::from("null");
        while Instant::now() < deadline {
            title = window::evaluate(&win, "document.title");
            if title == expected {
                break;
            }
            thread::sleep(Duration::from_millis(250));
        }
        thread::sleep(Duration::from_millis(800)); // let it finish painting
        let saved = window::snapshot(&win, &out) && Path::new(&out).is_file();
        let named = title == expected;
        println!("title: {title}");
        println!("{}", if saved { format!("saved {out}") } else { "couldn't take a picture".into() });
        std::process::exit(if saved && named { 0 } else { 1 });
    });
}
