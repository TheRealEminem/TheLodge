# The desktop app (Windows and Linux)

One [Tauri 2](https://tauri.app) app that does for Windows and Linux what `mac/` does for the Mac: it starts and
watches the app's bundled server, shows the web app in its own window, and lives in the tray. Like the Mac app it
knows nothing about any one app: `build.rs` reads the app's `app.json` (name, id, env prefix, port, update repo),
and the icons come from the app's `identity/desktop` (made from `identity/mac/AppIcon.icns` by
`scripts/desktop-icons`). Taken from Trailmix's shell (`~/Code/Trailmix/desktop`), without its recorder. The plan
it's part of is `PORTING.md`.

| File | What it does | On the Mac |
| --- | --- | --- |
| `src/config.rs` | who the app is, where its data goes, "is our server answering?" | `AppConfig.swift` |
| `src/server.rs` | starts `python -m uvicorn core.server.app:app`, restarts it after a crash (3 in 2 minutes and it gives up, saying why), stops it politely on Quit | `BundledServer.swift` |
| `src/window.rs` | the window, the loading page, the page's bridge, links opening in the browser | `MainWindow.swift` |
| `src/app.rs` | the start-up order, the tray menu, a second copy using the first one's server | `HostApp.swift` |
| `src/login.rs` | open at login: the registry's Run key on Windows, `~/.config/autostart` on Linux | `SMAppService` |
| `src/selftest.rs` | `--version`, `--about`, `--window-test` for CI and for checking a real machine | `scripts/smoke-test.sh` |
| `src/os/` | Win32 calls (a job object, Ctrl+Break, the registry); Unix signals and Linux's GPU drawing rule | |

**Data** goes in `%LOCALAPPDATA%\<Name>\data` on Windows and `$XDG_DATA_HOME/<Name>` (`~/.local/share/<Name>`) on
Linux, beside where `core/server/family.py` looks for the family folder. `<PREFIX>_DATA_DIR` overrides it.

**The bridge.** The page calls `window.webkit.messageHandlers.app.postMessage(…)`, as in the Mac app. The window's
initialization script makes that object and sends each message to the `shell://` protocol (`http://shell.localhost`
on Windows), so `core/web/api.ts` works unchanged. The server is told `<PREFIX>_SHELL=desktop` and what the shell can
do (`server.rs`'s `CAN`), and the web app hides the rest (`can()` in `core/web/api.ts`).

**Inside the installed app**, beside the program: `python/` (python-build-standalone), `app/` (`core`, `modules`,
`app.json`, `VERSION`), `ui/` (the built web app) and `bin/` (helpers, if any). The build script stages these and
passes them to Tauri with `--config` (chunk 5), so a development build needs none of them.

## Working on it

Rust is on the Mac (see `PORTING.md`). From `desktop/src-tauri`:

```
cargo check                                                                    # the shared code, on the Mac
RC=../dev/llvm-rc-stub cargo clippy --target x86_64-pc-windows-msvc           # the Windows code too
cargo run                                                                      # a development run
```

A development run has no bundled server: it shows whatever answers on the app's port (or `<PREFIX>_SERVER_URL`),
such as the installed Mac app or `scripts/dev`. Linux-only code (WebKitGTK) is checked by CI only.
