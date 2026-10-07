# Modern Midnight Commander

An enhanced version of [Midnight Commander](https://github.com/MidnightCommander/mc),
based on MC 4.8.33, with convenient file actions and refreshed themes.
The `mc-modern` branch contains the changes on top of the upstream release.
The original documentation remains in `README`.

The standard installation includes GIO trash actions, Wayland clipboard support,
four DotName skins, automatic red variants for root, and live skin switching.
These features include default shortcuts and work without a home configuration.
[Feature details and tests](dotname/README.md).

## See it in action

![Modern Midnight Commander demo](2026-10-07%2000-01-04.gif)

![Modern Midnight Commander alongside the desktop file manager](2026-10-07%2000-06-08.gif)

## Nix and NixOS

With Nix installed, enable `nix-command` and `flakes` in your user configuration
at `~/.config/nix/nix.conf` (create the directory and file if needed):

```ini
experimental-features = nix-command flakes
```

If `experimental-features` is already configured, add these values to the existing
setting. This takes effect for subsequent Nix commands without a system rebuild.
Then run:

```bash
nix run github:tomasmark79/mc
nix build github:tomasmark79/mc#mc
nix profile add github:tomasmark79/mc#mc
```

The first command runs MC, the second builds it and creates a `result` symlink,
and the third adds it to your user profile. Nix also works on Debian and other
Linux distributions. The flake exposes `x86_64-linux` and `aarch64-linux` packages;
binary availability depends on a cache or your own builder.
The Nix package includes libzip and enables direct ZIP reading for F5 copies.

Add this input to your NixOS flake:

```nix
mc-modern = {
  url = "github:tomasmark79/mc/mc-modern";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

Then add `mc-modern.packages.${pkgs.stdenv.hostPlatform.system}.mc` to
`environment.systemPackages`. Make the input available to the module, for
example through `specialArgs`. The source revision is pinned in `flake.lock`
and only changes when you update it explicitly.

## Building on Debian without Nix

Example dependencies and source build:

```bash
sudo apt-get install git build-essential autoconf automake libtool pkg-config \
  gettext autopoint libglib2.0-dev libslang2-dev libssh2-1-dev libgpm-dev \
  libx11-dev libext2fs-dev libaspell-dev libzip-dev python3 libglib2.0-bin \
  wl-clipboard perl zip unzip

git clone --branch mc-modern https://github.com/tomasmark79/mc.git
cd mc
./autogen.sh
./configure --prefix="$HOME/.local"
make -j"$(nproc)"
make install
"$HOME/.local/bin/mc"
```

ZIP extraction through F5 uses the fast direct-reading path when `configure`
finds libzip >= 1.0 through pkg-config. Install `libzip-dev` before configuring
and compiling MC. Without it, the build still succeeds, but ZIP copies use the
slower external helper and temporary files. Installing the library after MC
has been built does not enable the fast path: rerun `./configure`, `make`, and
`make install`. The `zip` and `unzip` tools are still needed for helper operations.

After configuring, verify that direct ZIP reading was enabled:

```bash
grep '^#define HAVE_LIBZIP 1' config.h
```

Installing into `~/.local` requires no root privileges and does not overwrite
`/usr/bin/mc`. Add `~/.local/bin` to `PATH` to launch this version as `mc`.
Standard `make install DESTDIR=...` is supported for system packaging.
This fork does not currently provide prebuilt `.deb` packages or an APT repository.

Clipboard actions require a running Wayland session and `wl-copy`; X11 and
clipboard forwarding over SSH are not implemented. Trash actions require `gio`.
MC itself also works without an accessible desktop clipboard. Personal bookmarks
and history are not included in this repository; an existing MC profile can
override the fork's defaults.

## Synology DSM

For a native Synology DSM SSH build targeting DS223j (`rtd1619b`), see the
[build and runtime instructions](synology/README.md).

## Shell integration

After installing MC so that `which mc` finds this fork, add the following to
`~/.bashrc`:

```bash
alias mc='source "$(dirname "$(readlink -f "$(which mc)")")/../libexec/mc/mc-wrapper.sh"'
```

Open a new terminal or run `source ~/.bashrc` to apply the settings.
The alias sources MC's shell wrapper so your shell stays in the directory you
were browsing when you exit MC. Resolving the executable's symlink locates the
wrapper in the same installation, including when MC comes from a Nix profile.
This path assumes the `libexec/mc` layout used by this fork's Nix package and
the default source installation. It also requires `which` and `readlink`.

The alias applies to the installed `mc` command. A one-off
`nix run github:tomasmark79/mc` launches MC directly and does not change the
parent shell's working directory on exit.

## Local development and maintenance

```bash
nix build .#mc
nix run .#mc-tests
```

Tests require Linux with user namespaces enabled and must run as a regular user.
They do not write to the actual desktop clipboard. To test a native build, set
`MC_TEST_BINARY` to the absolute path of the installed MC and `MC_TEST_HELPER`
to `misc/mc-clipboard.py`, make `python3`, `tmux`, and `unshare` available,
and run `python3 dotname/tests/run.py`.

Keep changes local until they have been reviewed and tested.
Merge upstream fixes into the `mc-modern` branch and verify the build and regression
tests. The archive version is stored in `dotname/VERSION`.
The original license terms remain in effect; see `COPYING`.
