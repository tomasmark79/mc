# Real TUI tests run explicitly, outside the build sandbox.
{ pkgs, mc }:
pkgs.writeShellApplication {
  name = "mc-tests";
  runtimeInputs = [
    pkgs.python3
    pkgs.tmux
    pkgs.util-linux
    pkgs.coreutils
  ];
  text = ''
    export MC_TEST_BINARY=${mc}/bin/mc
    export MC_TEST_HELPER=${../misc/mc-clipboard.py}
    exec python3 ${../dotname/tests/run.py} "$@"
  '';
}
