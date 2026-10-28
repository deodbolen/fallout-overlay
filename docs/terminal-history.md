# Terminal history and plain-text export

## Investigation

The SSH TUI used `TerminalScreen(pyte.Screen)`, which models only the visible
terminal viewport. On a 25-row terminal, feeding 200 newline-separated numbered
lines with no final newline leaves only 176–200 in that screen. Increasing an
SSH output buffer or changing the server's Python buffering cannot restore rows
the emulator has discarded.

`Session` separately kept the latest 4 MiB of raw bytes. This buffer was neither
a scrollback model nor a source for selection or copying. Its cap did not explain
the 100/200-line reproductions. The TUI renderer also wrote a space for every
unused cell, creating padding in externally selected terminal text.

The desktop host already requested `Vte.Format.TEXT` for selection copying.
No Markdown serializer, HTML encoder, or URL escaping was found in the terminal
copy path. Markdown-escaped delimiters, modified URLs, and newly introduced HTML
entities could not be reproduced there. They may be introduced by a downstream
clipboard/paste destination; the exported UTF-8 file is the reference for checking
this. The fix deliberately does not unescape literal source text: an application
printing `&amp;`, a backslash, or Markdown must keep those literal characters.

VTE's `get_text()` and the accessibility text used for some display operations
cover the visible view. Full-history copy/export now uses
`write_contents_sync()`, whose contract includes retained scrollback.

## Retention and interactive behavior

- Settings → Display → Terminal scrollback accepts 10,000–100,000 lines.
- Default retention is 10,000. In the TUI, wrapped fragments share their original
  logical line's retention slot, so wrapping does not prematurely evict earlier
  commands. This guarantees at least 10,000 archived visual rows; heavily wrapped
  lines can consume more memory. The live viewport is additional.
- Each TUI session owns its emulator, history, cursor, and snapshot. There is no
  global terminal transcript. Native VTE widgets also retain separate histories.
- Narrowing/widening a TUI terminal reflows complete logical lines while
  preserving text, styles, and cursor placement.
- Alternate-screen applications keep their working screen separate from normal
  shell history. Returning restores the normal screen, even after resizing.
- New output does not jump a scrolled TUI view back to the bottom. Typing into
  the live shell does return the view to current output.
- An explicit terminal scrollback-clear sequence (CSI 3 J) still clears history,
  as normal terminal semantics require. Closing/removing a session still ends
  that session; this change is not persistent recording across application exits.
- Native VTE applies capacity updates live. Existing TUI sessions apply the
  current setting when next attached; new sessions use it immediately.

## Using history, selection and export

### SSH TUI

Inside an attached session, F3/F4 or Shift+Page Up/Down scroll retained rows.
The footer shows when viewing history. Normal Page Up/Down remain available to
the foreground program. Mac keyboards may require Fn for function keys.

**For ordinary mouse copying on Apple Terminal, press F5 (often Fn+F5).**
This opens Copy view: the TUI temporarily steps aside and prints one continuous
plain-text snapshot between BEGIN/END markers. The client terminal owns the
scrolling, soft wrapping and selection, so you can select across screens and copy
once instead of repeatedly copying TUI viewports. Press Enter after copying to
resume the same session. Output capture continues in the background; the snapshot
is stable. No file is created, existing client scrollback is never cleared, and
clipboard permissions or custom key mappings are not required. The client
terminal's own scrollback limit still applies to this view; file export remains
available for histories larger than that limit.

For selection or export, press Ctrl+] to return to the navigator, select the
session in Terminal, and press M. Available actions include:

- **View history / select text:** a stable snapshot of this session's full
  retained text. Up/Down and Page Up/Down navigate, Home/End jump, and Left/Right
  pan long lines. Space marks the start of a selection; move to its end and press
  Enter for Copy, Export, or Select all. Selection operates on actual text lines,
  not the padded view or bytes of a Unicode character.
- **Copy view:** the same F5 view, available from the session menu or for a
  selected range of history lines.
- **Copy all plain text:** explicitly requests the client terminal's clipboard
  with OSC 52. Some terminal clients, including configurations of Apple Terminal,
  block or do not support remote clipboard requests. The UI reports a request,
  not guaranteed clipboard success; use file export when unsupported. Large
  clipboard requests are rejected with an export suggestion rather than clipped.
- **Export plain text:** saves the complete retained text as UTF-8. The default
  name identifies the session. Existing files are never overwritten, and new
  files use mode 0600. On SSH the file is on the SSH server, not the client Mac.

The display may wrap text, but export joins soft wraps and preserves actual line
boundaries. Literal Markdown, URLs, entities, combining marks, CJK characters,
and emoji are not converted. Display padding and ANSI controls are not exported.

### Desktop VTE

The terminal context menu offers **Copy**, **Copy all plain text**, and
**Export plain text**. The latter two include the widget's retained scrollback,
not just visible rows. The clipboard is populated as plain text. VTE's normal
mouse selection, Select all, reflow, and alternate-screen handling remain active;
output does not automatically scroll a user's selection away.

## Validation

Run the focused regression set from the checkout:

```sh
PYTHONPATH=scripts python3 -m unittest test_terminal_history \
  test_terminal_history_integration test_terminal_display \
  test_session_switching test_navigator test_path_completion \
  test_text_entry test_ssh_sounds
```

Coverage includes the 100/200-line reproductions, the 10,000-row floor, more than
10,000 wrapped visual fragments, independent per-session retention, resize
and alternate-screen round trips, byte-split UTF-8/emoji, ANSI removal, literal
URLs/markup/entities, no visual padding, private non-overwriting export,
clipboard payload bytes, and bracketed-paste shortcut isolation.

The integration test launches the actual TUI and two actual PTY shells. It
generates 200 long Unicode lines, scrolls to the first/last line, exports through
the navigator menu, checks all numbered lines and literal characters, and checks
that a second session's export contains none of the first session's output.

These checks run locally without an SSH server or GTK desktop. Native VTE API
selection is unit-tested with a test double; real Ubuntu 24.04 desktop clipboard,
mouse selection, and remote-client clipboard permissions still need target
verification.
