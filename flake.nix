{
  description = "Convert untrusted PDFs to safe image-only PDFs by rendering them in a disposable VM";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      overlays.default = final: prev: {
        vm-convert-pdf = final.callPackage ./package.nix { };
      };

      packages = forAllSystems (pkgs: rec {
        vm-convert-pdf = pkgs.callPackage ./package.nix { };
        default = vm-convert-pdf;
        guest-initrd = vm-convert-pdf.guest.initrd;
        guest-kernel = vm-convert-pdf.guest.kernel;
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/vm-convert-pdf";
        };
      });

      checks = forAllSystems (pkgs: {
        package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
        end-to-end = pkgs.callPackage ./tests/end-to-end.nix {
          vm-convert-pdf = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
        };
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
