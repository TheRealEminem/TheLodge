//! The app's own window (MainWindow.swift on the Mac): the web app in WebView2 on Windows and WebKitGTK on
//! Linux, so no browser is involved. Closing it leaves the tray icon; links to other sites open in your browser.
//!
//! The page talks to the shell through `window.webkit.messageHandlers.app.postMessage(…)`, the bridge the Mac
//! app offers (core/web/api.ts), so the web app needn't know which shell it's in. Here the initialization script
//! makes that object, and it sends each message to the shell:// protocol:
//!   "quit"            quit the app
//!   "reveal:<path>"   show a file or folder in File Explorer or the file manager
//!   "updates:<what>"  Settings → Updates: get, check, install, skip, unskip, beta-on, beta-off, go-back, try-again.
//!                     The window answers each, every change after, and every page load, with an "app-updates" event
//!                     on the page whose detail is the updater's report (update.rs), as the Mac app does.

use std::borrow::Cow;
use std::sync::{Mutex, OnceLock};
#[cfg(windows)]
use std::sync::mpsc;
use std::time::Duration;

use tauri::webview::{NewWindowResponse, PageLoadEvent};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_opener::OpenerExt;
use url::Url;

use crate::config;

pub const LABEL: &str = "main";
/// Where the bundled loading page lives (Tauri serves `frontendDist` here on Windows, tauri:// elsewhere).
#[cfg(windows)]
const LOADING_PAGE: &str = "http://tauri.localhost/index.html";
#[cfg(not(windows))]
const LOADING_PAGE: &str = "tauri://localhost/index.html";
/// Where the page reaches the shell:// protocol.
#[cfg(windows)]
const BRIDGE: &str = "http://shell.localhost/message";
#[cfg(not(windows))]
const BRIDGE: &str = "shell://localhost/message";

const BRIDGE_SCRIPT: &str = r#"(() => {
  window.__shellAppName = __NAME__;
  const send = (message) => {
    try { fetch('__BRIDGE__?m=' + encodeURIComponent(String(message)), { mode: 'no-cors' }).catch(() => {}); } catch (e) {}
  };
  window.webkit = window.webkit || {};
  window.webkit.messageHandlers = window.webkit.messageHandlers || {};
  window.webkit.messageHandlers.app = { postMessage: send };
})();"#;

/// The server the window shows: navigations within it stay in the window, anything else opens in the browser.
fn allowed() -> &'static Mutex<Option<Url>> {
    static ALLOWED: OnceLock<Mutex<Option<Url>>> = OnceLock::new();
    ALLOWED.get_or_init(|| Mutex::new(None))
}

fn same_site(a: &Url, b: &Url) -> bool {
    a.scheme() == b.scheme() && a.host_str() == b.host_str() && a.port_or_known_default() == b.port_or_known_default()
}

fn is_ours(url: &Url) -> bool {
    if matches!(url.scheme(), "about" | "tauri" | "data" | "blob") || url.host_str() == Some("tauri.localhost") {
        return true;
    }
    match allowed().lock().unwrap_or_else(|e| e.into_inner()).as_ref() {
        Some(site) => same_site(site, url),
        None => matches!(url.host_str(), Some("127.0.0.1") | Some("localhost") | Some("[::1]")),
    }
}

/// Links the self-test caught instead of opening: it runs on build machines, where a browser opening helps nobody.
static CAUGHT: Mutex<Option<Vec<String>>> = Mutex::new(None);

pub fn catch_links() {
    *CAUGHT.lock().unwrap_or_else(|e| e.into_inner()) = Some(Vec::new());
}

fn open_outside(app: &AppHandle, url: &str) {
    if let Some(caught) = CAUGHT.lock().unwrap_or_else(|e| e.into_inner()).as_mut() {
        caught.push(url.to_string());
        return;
    }
    let _ = app.opener().open_url(url, None::<&str>);
}

/// Makes the window (hidden) showing the loading page. Closing it hides it; the app lives on in the tray.
pub fn create(app: &AppHandle) -> tauri::Result<WebviewWindow> {
    let opener = app.clone();
    let new_window_opener = app.clone();
    let name = serde_json::to_string(config::NAME).unwrap_or_else(|_| "\"\"".into());
    let window = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::App("index.html".into()))
        .title(config::NAME)
        .inner_size(1280.0, 860.0)
        .min_inner_size(420.0, 560.0)
        .center()
        .visible(false)
        .initialization_script(BRIDGE_SCRIPT.replace("__BRIDGE__", BRIDGE).replace("__NAME__", &name))
        .on_navigation(move |url| {
            if is_ours(url) {
                return true;
            }
            open_outside(&opener, url.as_str());
            false
        })
        // A link for a new window (target=_blank, window.open) opens in your browser, as on the Mac. Without this
        // WebKitGTK drops it and the link does nothing.
        .on_new_window(move |url, _| {
            open_outside(&new_window_opener, url.as_str());
            NewWindowResponse::Deny
        })
        // The page's Copy buttons: page access to the clipboard is off by default on Windows and Linux.
        .enable_clipboard_access()
        .on_page_load(move |window, payload| {
            if payload.event() == PageLoadEvent::Finished {
                send_updates(window.app_handle());
            }
        })
        .build()?;
    let hide = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = hide.hide();
        }
    });
    Ok(window)
}

fn window(app: &AppHandle) -> Option<WebviewWindow> {
    app.get_webview_window(LABEL)
}

/// Shows the window at `target`. If it already shows that server, only the part after # changes (a page), so
/// the page doesn't reload.
pub fn show(app: &AppHandle, target: &str) {
    let Some(window) = window(app) else { return };
    if let Ok(url) = Url::parse(target) {
        let same = window.url().ok().map(|c| same_site(&c, &url)).unwrap_or(false);
        if same {
            if let Some(fragment) = url.fragment() {
                let hash = serde_json::to_string(&format!("#{fragment}")).unwrap_or_default();
                let _ = window.eval(format!("location.hash = {hash}"));
            }
        } else {
            *allowed().lock().unwrap_or_else(|e| e.into_inner()) = Some(url.clone());
            let _ = window.navigate(url);
        }
    }
    let _ = window.show();
    let _ = window.unminimize();
    let _ = window.set_focus();
}

/// Reloads the page (the server came back after another copy of the app stopped it).
pub fn reload(app: &AppHandle) {
    if let Some(window) = window(app) {
        let _ = window.eval("location.reload()");
    }
}

/// Shows the loading page, while the server starts.
pub fn show_loading(app: &AppHandle) {
    let Some(window) = window(app) else { return };
    let showing_it = window.url().map(|u| u.as_str().starts_with(LOADING_PAGE)).unwrap_or(false);
    if !showing_it {
        if let Ok(url) = Url::parse(LOADING_PAGE) {
            let _ = window.navigate(url);
        }
    }
    let _ = window.show();
    let _ = window.set_focus();
}

/// Says on the loading page why the server didn't start.
pub fn loading_failed(app: &AppHandle, text: &str) {
    if let Some(window) = window(app) {
        let text = serde_json::to_string(text).unwrap_or_default();
        let _ = window.eval(format!("window.shellFailed && window.shellFailed({text})"));
    }
}

/// Messages from the page (see the top of this file).
pub fn bridge(app: &AppHandle, request: tauri::http::Request<Vec<u8>>) -> tauri::http::Response<Cow<'static, [u8]>> {
    let uri = request.uri();
    if uri.path() == "/message" {
        let message = uri
            .query()
            .and_then(|q| url::form_urlencoded::parse(q.as_bytes()).find(|(k, _)| k == "m").map(|(_, v)| v.into_owned()))
            .unwrap_or_default();
        handle_message(app, &message);
    }
    tauri::http::Response::builder()
        .status(200)
        .header("Access-Control-Allow-Origin", "*")
        .header("Content-Type", "text/plain")
        .body(Cow::Borrowed(b"ok" as &[u8]))
        .unwrap()
}

fn handle_message(app: &AppHandle, message: &str) {
    if message == "quit" {
        crate::app::quit(app);
    } else if let Some(what) = message.strip_prefix("updates:") {
        crate::app::updates_command(app, what);
    } else if let Some(path) = message.strip_prefix("reveal:") {
        if std::path::Path::new(path).exists() {
            let _ = app.opener().reveal_item_in_dir(path);
        }
    }
}

/// Tells the page where updates stand (Settings → Updates listens for "app-updates"). Nothing without an updater.
pub fn send_updates(app: &AppHandle) {
    let Some(updater) = app.try_state::<crate::app::AppState>().and_then(|s| s.updater.clone()) else { return };
    let Some(window) = window(app) else { return };
    let detail = updater.report().to_string();
    let _ = window.eval(format!("window.dispatchEvent(new CustomEvent('app-updates', {{ detail: {detail} }}))"));
}

/// The script `evaluate` runs: the expression's value as JSON text, "null" if it threw.
#[cfg(windows)]
fn evaluation(script: &str) -> String {
    format!("(() => {{ try {{ return JSON.stringify((() => {{ return {script} }})()) ?? 'null' }} catch (e) {{ return 'null' }} }})()")
}

/// Runs JavaScript in the page and returns its result as JSON text ("null" if there's no page or it threw).
#[cfg(windows)]
pub fn evaluate(window: &WebviewWindow, script: &str) -> String {
    let (tx, rx) = mpsc::channel::<String>();
    let js = windows::core::HSTRING::from(evaluation(script));
    let run = window.with_webview(move |webview| unsafe {
        let Ok(core) = webview.controller().CoreWebView2() else { return };
        let handler = webview2_com::ExecuteScriptCompletedHandler::create(Box::new(move |outcome: windows::core::Result<()>, result: String| {
            let _ = tx.send(if outcome.is_ok() { result } else { "null".into() });
            Ok(())
        }));
        let _ = core.ExecuteScript(&js, &handler);
    });
    if run.is_err() {
        return "null".into();
    }
    // ExecuteScript gives the JSON of the JS value, and our wrapper returns a string of JSON: unwrap one layer.
    match rx.recv_timeout(Duration::from_secs(15)) {
        Ok(encoded) => serde_json::from_str::<String>(&encoded).unwrap_or_else(|_| "null".into()),
        Err(_) => "null".into(),
    }
}

/// Saves what the window shows as a PNG.
#[cfg(windows)]
pub fn snapshot(window: &WebviewWindow, path: &str) -> bool {
    let (tx, rx) = mpsc::channel::<bool>();
    let file = windows::core::HSTRING::from(path);
    let run = window.with_webview(move |webview| unsafe {
        use webview2_com::Microsoft::Web::WebView2::Win32::COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG;
        use windows::Win32::System::Com::IStream;
        use windows::Win32::UI::Shell::SHCreateStreamOnFileEx;
        const STGM_WRITE_CREATE: u32 = 0x0000_0001 | 0x0000_1000;
        const FILE_ATTRIBUTE_NORMAL: u32 = 0x80;
        let Ok(core) = webview.controller().CoreWebView2() else {
            let _ = tx.send(false);
            return;
        };
        let Ok(stream) = SHCreateStreamOnFileEx(&file, STGM_WRITE_CREATE, FILE_ATTRIBUTE_NORMAL, true, None::<&IStream>) else {
            let _ = tx.send(false);
            return;
        };
        let keep = stream.clone();
        let handler = webview2_com::CapturePreviewCompletedHandler::create(Box::new(move |outcome: windows::core::Result<()>| {
            drop(keep); // the file is complete once the capture is
            let _ = tx.send(outcome.is_ok());
            Ok(())
        }));
        // If this fails the handler (and with it the sender) is dropped, which reads as "no".
        let _ = core.CapturePreview(COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG, &stream, &handler);
    });
    if run.is_err() {
        return false;
    }
    rx.recv_timeout(Duration::from_secs(20)).unwrap_or(false)
}

/// Linux's (WebKitGTK) and the Mac's evaluate and snapshot come with the Linux build (PORTING.md, chunk 8).
#[cfg(not(windows))]
pub fn evaluate(_window: &WebviewWindow, _script: &str) -> String {
    "null".into()
}

#[cfg(not(windows))]
pub fn snapshot(_window: &WebviewWindow, _path: &str) -> bool {
    let _ = Duration::from_secs(0);
    false
}
