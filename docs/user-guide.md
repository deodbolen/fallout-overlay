# Fallout XFCE user guide

A bright green-on-black XFCE theme, 36px system panel, and full-height F12 drop-down terminal. The embedded navigator is 16pt, regular session views are 14pt, and Nano views are 11pt; desktop and panel text are 12pt.

Run `./install.sh` from a terminal in your XFCE desktop session. Run `./restore.sh` to restore your original settings. Installation preserves the first backup at `~/.local/state/fallout-ui/original`; repeating installation does not overwrite it. Keep this project directory in place: the panel, terminal launcher, and wallpaper reference its files.

The top bar shows CPU, RAM, home-filesystem free space, aggregate physical disk read/write rates, network receive/send rates, CPU temperature, and battery where available. Hover for details. Metrics refresh every two seconds with no persistent collector. The first sample has zero rates until the next refresh. Disk counters exclude partitions, loop devices, and device-mapper devices to avoid counting layered storage twice. Network includes non-loopback interfaces.

F12 opens the navigator. Left/Right cycles through **HOME → SSH → TERMINAL → APPLICATIONS → ⚙ SETTINGS**. Up/Down selects a row, Enter opens it, and Backspace returns to the parent menu. In Home, Enter expands/collapses folders. Select a file and press Ctrl+M (or M) for Rename, Copy, Move, SCP, Delete, Compress, File info, Open, and Cancel. Enter or O opens text documents in Nano in a new embedded local terminal session. After exiting Nano, a shell remains open in the document’s directory. Non-text files use their desktop viewer. The embedded host distinguishes Ctrl+M from Enter, so Ctrl+M opens the file menu and Enter opens the document. Copy and Move prompt for an existing destination directory with live directory suggestions. Tab completes the path, Up/Down selects a suggestion, and Tab applies it. Ctrl+U clears the field; Enter accepts it. Only directories are suggested, including hidden directories when you type a dot; relative paths start at the source directory. Existing destination files are never overwritten. Delete moves the file to the desktop Trash after confirmation. Compress creates a sibling `.zip` archive and keeps the original. SCP is a placeholder for a later update. Ctrl+N on a selected directory lets you choose Directory or File, enter a name, then Create or Cancel. New files are empty; existing items are never overwritten. The newly created item is highlighted. H toggles hidden files, and S opens an embedded shell at the selected directory.

In SSH, open HOST for **+ Host** and the saved hosts. The host form has common name, IP/FQDN, optional username, and optional saved key; select a field and press Enter to edit it. A blank username uses your logged-in username; no key means password authentication. Select a saved host for Connect, Edit, Push new key, or Cancel.

SSH-KEY offers Generate new key and Saved keys. Generation creates an Ed25519 key under `~/.ssh/fallout_NAME`; OpenSSH asks for an optional passphrase. A saved key offers Push to host, Revoke, or Cancel. Push lets you select a host and change the remote directory (default `~/.ssh`), then appends only the public key to `authorized_keys` without duplicating it. After a successful push the host uses that key. A custom directory must match the remote server's authorized-key configuration. Revoke removes that public key from all successful pushes tracked by this app, preserves other keys, and keeps the local key. Failed revocations stay tracked for retry; manually installed keys on untracked hosts are not removed.

Connections, local shells, key generation, pushes, and revocations run inside the **TERMINAL** section. A fixed reminder at the bottom stays visible while commands scroll or clear the screen. **Ctrl+]** returns to the navigator while a session keeps running; select it and press Enter to resume. While inside a terminal, Ctrl+Up switches to the previous running session and Ctrl+Down switches to the next, wrapping around and skipping finished sessions. SSH prompts for passwords, key passphrases, and host verification normally. If the selected key is rejected, the session offers to push it; network failures do not trigger a push. Passwords and passphrases are not saved. Closing the navigator with active sessions asks whether to close them. Sessions do not survive quitting the navigator; each session has a native VTE widget that retains its screen, scrollback, and font when switching. The fixed reminder is a separate widget below the session. After exiting Nano, its view returns to the 14pt local shell font.

APPLICATIONS lists installed desktop applications. GUI apps launch normally, and command-line apps run in the Terminal section. The SSH catalog is saved in `~/.config/fallout-ui/ssh.json` with mode 600, and operation status is stored under `~/.local/state/fallout-ui/sessions`. These are separate from the desktop restoration backup.

A custom F12 binding is preserved by using Ctrl+Alt+F12 instead. Shell aliases and preferences from `.bashrc` are loaded before the welcome and green prompt. Close an older navigator with Q and press F12 again to load updated code.

Restore recovers the captured desktop channels and terminal/panel files. It also restores any previous theme under the same name. Changes made to those settings after installation are replaced when restoring. The backup remains available afterward.

Checks: `python3 scripts/test_navigator.py`, `python3 scripts/test_metrics.py`, `python3 -m py_compile scripts/*.py`, and `sh -n install.sh restore.sh scripts/terminal.sh`.

The terminal renderer bundles unmodified Debian pyte 0.8.0 and wcwidth 0.2.13 under `vendor/python`; license notices are in `vendor/licenses`. No system-wide Python package installation is required. Footer checks: `python3 scripts/test_terminal_display.py`.

File-action checks: `python3 scripts/test_file_actions.py`.

A faint static CRT scanline overlay covers the desktop, including applications and the navigator. It uses transparent GTK windows with an empty input region, so clicks pass through and keyboard focus stays with your apps. It is opt-in via `python3 scripts/install_crt.py`; the main installer does not enable it. Once enabled, it starts at login via `~/.config/autostart/fallout-crt.desktop`, supports monitor changes, and allows only one running instance. `restore.sh` stops it and restores the prior autostart file. Temporarily stop it with `/usr/bin/python3 scripts/crt_overlay.py --stop`; start it again with `/usr/bin/python3 scripts/crt_overlay.py` from your desktop session. Intensity is `OPACITY` in `scripts/crt_overlay.py` (currently 0.065).

The overlay reapplies its empty input region after mapping, resizing, and stacking changes and verifies the X11 SHAPE input region directly. If verification fails, the overlay closes. Settings checks: `python3 scripts/test_settings.py`.

Settings also includes **CRT scan animation**, independently enabled/disabled from static scanlines. Five closely spaced, faint green scan lines sweep downward every 12 seconds at about 30 frames per second, with soft phosphor glow, a fading trail, and gentle brightness variation. Both choices persist across logins; the overlay process stops when both effects are disabled. The moving band uses the same verified click-through windows as the static overlay.

Changing sections plays a brief (~150 ms) green static burst and scan sweep, then restores the clean new screen. Navigation input is kept queued during the transition.

The F12 launcher runs `scripts/embedded_app.py`: one GTK window with a 16pt navigator VTE and one independent VTE per terminal session. Nano uses 11pt without changing other views. F12 hides/shows the existing window without stopping sessions. The navigator communicates with the host over a mode-600 local Unix socket; peers must have the same user ID. The installer supplies the system VTE typelib matched to its library; `vendor/typelib` remains a fallback for existing installations. The curses/PTy renderer remains available as a fallback when running `scripts/browser.py` directly. Real GUI checks are `scripts/test_embedded_gui.py` and `scripts/test_embedded_rpc.py`, run using `/usr/bin/python3` from an XFCE session.

In the file menu, **Open GUI** (below Open) uses the default desktop application. **Open with >** lets you enter a full executable path or Browse for one, then choose Open or Cancel. The selected file is passed as a separate argument, including paths containing spaces. Open and Enter continue to use the embedded Nano editor for text documents.

Press **O** on a highlighted directory to open a new embedded local terminal session starting in that directory. On a file, O opens the document as before.

Switching between embedded terminal sessions shows a brief, silent green static burst and scan sweep. The effect lasts about 240 ms and passes clicks through to the terminal.

In embedded terminal sessions, **Ctrl+Shift+C** copies selected text, **Ctrl+Shift+V** pastes, and **Ctrl+Shift+A** selects all output including scrollback. Right-click also offers Copy, Paste, and Select all. Copy is available when text is selected.

**Shift+Up/Down** extends or reduces a keyboard text selection from the terminal cursor by one line. Use **Ctrl+Shift+C** to copy it.

Opening a GUI application from Applications, Open GUI, Open with, or a binary document automatically hides the navigator. **F12** brings it back; terminal sessions keep running.

Sound files in `fallout-sounds` play through the installed GStreamer audio backend. The desktop CRT process owns a quiet looping fan hum and stops it on exit. Navigator typing uses charscroll, menu rows use focus/OK/cancel, section changes use Pip-Boy select plus randomized static, terminal switches use static, and F12 show/hide uses load. Playback is nonblocking, typing is rate limited, and sounds of the same kind cannot accumulate. Fan volume is 45%; effects are 85%.

In new local Bash sessions, ordinary `sudo command` validates credentials first, plays passgood on successful validation, then runs the command. Cached credentials also count as accepted. The English sudo retry message “Sorry, try again.” triggers passbad. Option-led sudo forms retain their usual behavior and do not trigger passgood; localized retry messages and remote SSH authentication are not covered. Password input is never recorded or sent to the sound service.

Pressing **Enter** (including numeric keypad Enter) inside a terminal session plays the menu confirmation sound and sends Enter to the running application normally.

**Backspace** plays charscroll, including when deleting text in terminal sessions or navigator input fields. Escape retains the cancel sound.

SSH Connect plays passgood immediately when OpenSSH enters its authenticated interactive session, and passbad on rejected authentication or connection failure. Password and key-based connections both have feedback, including reconnecting after a key push. A normal logout does not play failure. Verbose SSH diagnostics used for detection are suppressed; normal prompts and errors remain visible.

**Settings → Volume** controls sound effects and fan hum separately. Up/Down selects a control, **+/-** adjusts by 5%, and **Enter** lets you type an exact percentage. **0%** mutes that group. Changes save immediately and update both the navigator and active fan within 250 ms. Escape returns.

Fresh-machine installation: copy the entire project (including `fallout-sounds`, `logo`, `assets`, `theme`, and `vendor`) to a permanent directory. On Debian 13 XFCE, run `./install.sh` from a terminal in your logged-in X11 desktop, **without sudo**. The installer checks Debian package status, installs only missing dependencies using `sudo apt-get update` and `sudo apt-get install`, then checks GTK/VTE/audio support before backing up or changing desktop settings. Apt may ask for your sudo password and needs repository access. Run `./install.sh --check` for a read-only dependency check. A failed package install stops desktop installation. Installed system packages remain installed when restoring the desktop.

The project may live under another username or directory, including paths containing spaces. Runtime paths are derived from script locations; new installs use the system VTE typelib matched to the installed library. Debian derivatives may work but are not verified; this installer requires an existing XFCE X11 session.
