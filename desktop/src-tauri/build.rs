//! Bakes in who this app is, from the app's app.json (two folders up), as scripts/build-app.sh does for the Mac
//! app's Info.plist: its name, id, environment prefix, port and the GitHub repo its updates come from.
//! FAMILY_UPDATE_REPO overrides the repo (a test build pointed somewhere else).

use std::path::Path;

fn main() {
    let app_json = Path::new("../../app.json");
    println!("cargo:rerun-if-changed={}", app_json.display());
    println!("cargo:rerun-if-env-changed=FAMILY_UPDATE_REPO");
    let identity: serde_json::Value = std::fs::read_to_string(app_json)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    let text = |key: &str, default: &str| identity.get(key).and_then(|v| v.as_str()).unwrap_or(default).to_string();
    let port = identity.get("port").and_then(|v| v.as_u64()).unwrap_or(8790);
    let repo = std::env::var("FAMILY_UPDATE_REPO").ok().filter(|r| !r.trim().is_empty()).unwrap_or_else(|| text("updateRepo", ""));

    println!("cargo:rustc-env=FAMILY_APP_NAME={}", text("name", "Starter"));
    println!("cargo:rustc-env=FAMILY_APP_ID={}", text("id", "starter"));
    println!("cargo:rustc-env=FAMILY_APP_PREFIX={}", text("envPrefix", "STARTER"));
    println!("cargo:rustc-env=FAMILY_APP_PORT={port}");
    println!("cargo:rustc-env=FAMILY_UPDATE_REPO={}", repo.trim());
    tauri_build::build()
}
