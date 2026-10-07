# Synology DSM build

Native SSH build of Modern Midnight Commander for DS223j (`rtd1619b`, ARM64).
The build uses Synology's GCC 12.2/glibc 2.36 toolchain and DSM 7.4 development
libraries. It needs no Nix installation on the NAS.

## Build on a Linux PC

From this Git checkout on an x86_64 Linux PC with Nix:

```sh
nix develop .#dsm-build --command bash synology/build.sh
```

The script downloads and verifies the official toolchain and SDK, then builds
the current tracked source files. Downloads and build directories are kept in
`~/.cache/mc-dsm`; archives are written to `dist/synology`. Override these with
`MC_DSM_CACHE`, `MC_DSM_OUTPUT`, and optionally `MC_DSM_JOBS`.
On NixOS, running Synology's Linux compiler requires `nix-ld` with the compiler's
host libraries available. The build does not install anything on the NAS.

## Run on the NAS

Copy the archive to the NAS and extract it into a directory you own, for example:

```sh
mkdir -p "$HOME/.local/opt"
tar -xzf mc-modern-*-dsm7-rtd1619b.tar.gz -C "$HOME/.local/opt"
"$HOME/.local/opt/mc-modern/bin/mc" --version
"$HOME/.local/opt/mc-modern/bin/mc"
```

The launcher resolves its installation directory and sets paths for skins,
configuration, translations and helpers. Always use `bin/mc`, not `bin/mc.bin`.
Add the bundle's `bin` directory to `PATH` if you want to launch it as `mc`.
No root privileges or changes to DSM system directories are needed.

## Runtime dependencies and limitations

The binary uses the DSM system libraries, including GLib and ncurses. It is a
build for `rtd1619b`, not a universal package for every Synology model.
Use an SSH terminal with `TERM=xterm-256color` for the DotName skins.
The launcher uses bundled terminfo entries for `xterm-256color`,
`screen-256color`, and `tmux-256color`. Their color-pair count is capped at 32767
because the inspected DSM ncurses 6.1 reads the system entry's 65536 pairs as zero.
This fixes 256-color skin loading without changing DSM system files.
If `LANG` is unset, the launcher defaults to `en_US.UTF-8` for Unicode symbols.
For a Czech interface, run `LANG=cs_CZ.UTF-8 bin/mc` from the bundle directory.
DSM mounts `/tmp` with `noexec` on the inspected NAS; extract onto a data volume
or into your home directory rather than `/tmp`.
Existing MC user configuration can override this fork's defaults.

Wayland clipboard actions require a desktop session and do not forward the
clipboard over SSH. Trash actions require `gio`, which is absent on the inspected
DS223j; they do not implement DSM's shared-folder recycle bin. `F8` remains
permanent deletion. Archive helpers require their external programs, and several
require Perl. These tools are not bundled. The inspected NAS has no Perl or unzip.
The SDK does not supply libzip development headers, so this build uses the
standard external ZIP helper rather than the direct ZIP-reading optimization.

This archive is not a Package Center `.spk` and does not register a DSM service.
Installing, configuring shell startup files and publishing are separate steps.
