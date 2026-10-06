# Real TUI tests run explicitly, outside the build sandbox.
{ pkgs, mc }:
pkgs.writeShellApplication {
  name = "mc-tests";
  runtimeInputs = [
    pkgs.python3
    pkgs.tmux
    pkgs.util-linux
    pkgs.coreutils
    pkgs.unzip
    pkgs.zip
  ];
  text = ''
    export MC_TEST_BINARY=${mc}/bin/mc
    export MC_TEST_HELPER=${../misc/mc-clipboard.py}
    export MC_TEST_UZIP=${mc}/libexec/mc/extfs.d/uzip
    python3 ${../dotname/tests/zip_cache.py}
    exec python3 ${../dotname/tests/run.py} "$@"
  '';
}
