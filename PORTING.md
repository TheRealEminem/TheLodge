# Family apps on Windows and Linux

The plan for taking the family's apps off the Mac, following Trailmix's port ("Taking a Trailmix-family app
cross-platform", 4 November 2026). Trailmix's shell (`~/Code/Trailmix/desktop/src-tauri`, its `build-windows.py`,
`build-linux.py`, `smoke-test-*` and `release.yml`) is the reference for every chunk. Started 4 November 2026 from
The Lodge.

## Decisions

- **The shell lives here**, as `desktop/` beside `mac/`: one Tauri 2 app for Windows and Linux, driven by `app.json`
  like the Mac app, so every family app pins it and gets the platforms with it. Only the parts every app needs come
  from Trailmix (server, window and bridge, tray, open at login, updater, self-tests), not its recorder.
- **Always beta.** Windows and Linux builds stay pre-releases.
- **Cadence.** The Mac app moves on as it does now. Windows and Linux get a build when a major feature lands, plus bug
  fixes for that version, not every small Mac release. Their builds are started by hand (`workflow_dispatch`), not
  by every tag.
- **Builds run on GitHub's Windows and Linux runners.** The Mac app stays built on the Mac.
- **Rust on the Mac for writing the shell.** Rust is installed with rustup (minimal profile, clippy, rustfmt, and
  the `x86_64-pc-windows-msvc` and `aarch64-pc-windows-msvc` targets), so the shell's shared and Windows code is
  type-checked here in seconds instead of a round trip to CI:

  ```
  RC=desktop/dev/llvm-rc-stub cargo check --target x86_64-pc-windows-msvc
  ```

  Tauri compiles Windows' icon and version resources with `llvm-rc`, which the Mac lacks; `cargo check` never links,
  so the stand-in writes an empty one. (Tried on Trailmix's whole Windows shell: about 40 seconds the first time.)
  Linux-only code (GTK, WebKitGTK) can't be checked on a Mac and waits for CI. Nothing ships on a Mac compile: the
  real builds, installers and smoke tests are always CI's.
- **Nothing is signed** yet, on any platform.
- **Local AI off the Mac only with a GPU or NPU** that a supported framework can use (CUDA, ROCm, Vulkan, DirectML…).
  Without one, setup recommends a cloud model or your own plan: CPU and RAM alone are too slow.
- **Real testers** exist for Windows and Linux.

## Chunks

Each chunk ships on its own and is synced into the apps when they choose.

1. **Done 4 Nov 2026.** **Platform words and capability flags.** The server says which system it's on (`core/server/computer.py`) and
   the web app words things to match ("this Mac", "this PC", "this computer"; Finder or File Explorer; menu bar or
   system tray). The shell names itself and what it can do (`<PREFIX>_SHELL`, `<PREFIX>_SHELL_CAN`), and the web app
   hides what it can't (`can("updates")`) instead of showing broken buttons.
2. **Written 5 Nov 2026, not yet run on Windows.** **Local AI off the Mac.** The hardware readout (`resources.py`) finds a GPU or NPU and its framework; setup
   recommends local only with one. Ollama setup for Windows and Linux.
3. **Release files per platform and architecture** (`<App>-<version>-windows-x64.exe`, `-linux-x86_64.AppImage`…),
   and each updater picks its own.
4. **Done 4 Nov 2026.** **The desktop shell** (`desktop/src-tauri`, see `desktop/README.md`): identity from `app.json` (baked in by `build.rs`), the bundled
   server started and watched, the window with the same `webkit.messageHandlers.app` bridge the Mac offers, the tray,
   open at login, and `--version` and `--window-test` for CI.
5. **Done 4 Nov 2026** (The Lodge's run 41922239132 passed: a 36 MB installer, 157 MB installed; the first beta waits
   for the updater, chunk 6). **Windows x64**: `scripts/build-windows.py`, the CI job (build, install, window test), first beta.
6. **Done 5 Nov 2026** (The Lodge's run 41951852053: updated 0.0.1 to the new build with its own updater, then went
   back, the data kept each time). Windows is published by running desktop.yml on a release's tag. **The Windows updater** and the update-path test: install the current release, update to the new one, go back.
7. **Done 5 Nov 2026** (The Lodge's run 42098005409: a 32 MB installer, 148 MB installed, every compiled file ARM, fresh
   install, update and go back all passed). **Windows ARM** on GitHub's ARM runner.
8. **Linux**: built on Ubuntu 22.04 (glibc 2.35 and later), AppImage, .deb and .rpm, the Linux updater (the AppImage
   replaces itself; .deb and .rpm show a download link), smoke tests under Xvfb on Ubuntu and Debian, GPU drawing only
   where it's safe.
9. **Each app takes it**: sync, word its own modules for each platform, its own CI job, a beta per platform, and the
   download page lists a platform once its update test passes.

Intel Mac isn't planned; it's cheap to add (an x86_64 build smoke-tested under Rosetta) if anyone needs it.

## Rules while porting

- Shared by default. Platform code sits behind `cfg(windows)` or in `desktop/src-tauri/src/linux/`, each file
  mirroring its Swift counterpart (`server.rs` = `BundledServer.swift`, `update.rs` = `Updater.swift`).
- In Python: `os.path` and `pathlib` for paths, no `%-d` style date codes, `sys.platform` switches in one place,
  never `say`, `afplay`, `osascript` or `open`.
- Every bug that only the installed app on another platform found gets a self-test that would have caught it.
