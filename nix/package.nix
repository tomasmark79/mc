{
  lib,
  mc,
  autoreconfHook,
  gettext,
  python3,
  glib,
  libzip,
  wl-clipboard,
}:
mc.overrideAttrs (old: {
  version = lib.removeSuffix "\n" (builtins.readFile ../dotname/VERSION);
  src = lib.cleanSource ../.;
  # The fork source tree already includes the custom changes.
  patches = [ ];
  buildInputs = (old.buildInputs or [ ]) ++ [ libzip ];
  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
    autoreconfHook
    gettext
  ];
  postPatch = (old.postPatch or "") + ''
    substituteInPlace misc/mc-clipboard.py \
      --replace-fail '/usr/bin/env python3' '${python3}/bin/python3' \
      --replace-fail '"wl-copy"' '"${wl-clipboard}/bin/wl-copy"'
    substituteInPlace misc/mc-trash.menu \
      --replace-fail 'gio trash' '${glib.bin}/bin/gio trash'
  '';
  autoreconfPhase = ''
    runHook preAutoreconf
    ./autogen.sh
    runHook postAutoreconf
  '';
  meta = old.meta // {
    description = "Midnight Commander with trash actions, Wayland clipboard support, and DotName skins";
    homepage = "https://github.com/tomasmark79/mc";
    platforms = lib.platforms.linux;
  };
})
