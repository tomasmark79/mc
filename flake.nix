{
  description = "Modern Midnight Commander with DotName skins and enhanced file actions";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      eachSystem = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = eachSystem (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          mc = pkgs.callPackage ./nix/package.nix { };
        in
        {
          inherit mc;
          default = mc;
          mc-tests = import ./nix/tests.nix { inherit pkgs mc; };
        }
      );
      apps = eachSystem (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.mc}/bin/mc";
        };
      });
      checks = eachSystem (system: {
        build = self.packages.${system}.mc;
      });
      devShells = eachSystem (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            inputsFrom = [ self.packages.${system}.mc ];
            packages = [
              pkgs.python3
              pkgs.tmux
              pkgs.util-linux
              pkgs.glib
              pkgs.wl-clipboard
            ];
          };
        }
      );
    };
}
