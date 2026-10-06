# Midnight Commander customizations

This package includes custom trash and clipboard actions, cycling through
favorite skins, and automatic selection of DotName root skin variants.

## Defaults without a home configuration

Shortcuts, skins, and F2 menu entries are included in the package. They do not
require files in `~/.config/mc` or `~/.local/share/mc`. A new profile starts with
the light DotName skin; root uses its red variant. All four DotName skins
use the 256-color palette and do not require `COLORTERM=truecolor`.

| Action | Default shortcut |
|---|---|
| Switch between light and dark skins | `Alt+Shift+T` |
| Move to trash | `Delete`, `F12` |
| Delete permanently | `F8`, `Shift+Delete` |
| Copy full path | `Alt+Shift+F` |
| Copy parent directory path | `Alt+Shift+D` |
| Copy item name | `Alt+Shift+N` |
| Copy item to clipboard | `Alt+Shift+C` |

Clipboard actions operate on the item under the cursor, whether a file or a
directory. `Alt+Shift+D` copies the path of that item's parent directory.

When the command line contains text, `Delete` removes the character under the
cursor and does nothing at the end of the line. With an empty command line,
it moves the selection to trash. With no marked files, selecting `..` shows
the same error as native deletion. Marked files still take precedence over
the cursor position. `F12` opens the trash confirmation even while
a command is being entered.

Trash confirmation uses the same dialog formatting as native deletion: item
type and name for a single selection, or counts for files, directories, and
mixed selections. Long names are shortened in the same way. The `safe_delete`
setting selects No by default for both operations.

User configuration can override these defaults. Bookmarks, history, and other
personal settings remain user data. Clipboard actions require an accessible
Wayland session; running as root does not automatically grant desktop access.

## ZIP extraction

With libzip available at build time, F5 reads ZIP entries directly into MC's
normal copy loop. The archive stays open between files, eliminating per-file
helper processes and extracted temporary copies while retaining MC's selection,
overwrite dialogs, progress, and CRC error handling. Changes to the archive
invalidate the open index. Background jobs open their own archive handle.

Viewing, editing, custom user helpers, and entries that cannot use direct
reading retain the extfs helper. Its temporary filename index avoids listing
the entire archive for each extraction. MC removes the index when releasing
the archive; if caching is unavailable, the helper uses its original lookup.
The Nix package includes libzip. Source builds detect libzip >= 1.0 through
pkg-config during `./configure` and use the slower helper throughout when the
library is absent. On Debian, install `libzip-dev` before building. Installing
it after MC has been compiled does not enable direct reading; reconfigure,
rebuild, and reinstall MC. Check for `#define HAVE_LIBZIP 1` in `config.h` after
configuration. The `zip` and `unzip` tools remain necessary for helper operations.

## Repeatable tests

Run this command from the repository directory as a regular user:

```bash
nix run .#mc-tests
```

Nix builds MC from this fork and supplies the test dependencies. It does not
activate a system configuration. Run the tests after changing the customizations
or updating MC. Success ends with `OK`; failures return a nonzero exit status.

The tests cover:

- Actual cursor colors in a running MC for a regular user and effective UID 0.
- Clean user and root profiles, `skin=default`, explicit root variants,
  `MC_SKIN`, and `--skin`.
- Switching with `Alt+Shift+T`, preserving the marked file and second panel,
  and saving the base skin name on exit.
- Reloading the skin list at runtime, comments, duplicates, and restoring the
  previous appearance after a skin loading error.
- Cancelling trash operations and actually moving a test file through GIO,
  including its contents and `.trashinfo` file, without a supplied keymap.
- Deleting command-line characters with `Delete` and returning to the trash
  action once the line is empty; preserving `F12`, `F8`, and `Shift+Delete`.
- Invoking the clipboard helper through all four default shortcuts and the F2
  menu.
- Clipboard helper payloads for all four modes, MIME types, spaces, Unicode,
  symbolic links, process errors, timeouts, and interrupts.
- ZIP index reuse across helper processes, archive changes, concurrent readers,
  long paths, special filenames, and fallback when caching is unavailable.
- Direct F5 copying of 502 ZIP files without extracted temporary copies,
  changed archives, CRC errors, background copying, viewing before copying,
  custom helper and aliased-name fallback, and cache cleanup when MC exits.

MC runs in a separate tmux server without the user's tmux configuration.
Each scenario uses a temporary directory inside the home directory with its
own XDG configuration, data, and trash. These directories are removed afterward.
Using the home directory lets GIO use trash even when it refuses the filesystem
containing `/tmp`.

Root checks use `unshare --user --map-root-user`, not `sudo`. MC has effective
UID 0 inside that namespace without gaining root privileges on the host. If
user namespaces are disabled, the test exits with an explanation instead of
silently skipping root checks.

Clipboard unit tests replace `wl-copy` with a mock. Shortcut tests invoke the
real helper with an intentionally unavailable Wayland socket and check its
error. They do not modify the desktop clipboard or verify delivery to it;
after changing this integration, also check pasting text and files in the
desktop environment. The trash test does not cover remote VFS locations.
Tests run explicitly through `nix run`; they are not part of `nix flake check`
or every system build.

To run a single test:

```bash
nix run .#mc-tests -- RuntimeTests.test_themes
```
