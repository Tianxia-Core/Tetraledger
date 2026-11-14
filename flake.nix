# ffp: FFP-TETRALEDGER-FLAKE declarative nix
{
  description = "Tetraledger v8.7.0 — Tier-3 4-Way Cryptographic Merkle Settlement & HTTP 402 (x402) Micropayment Gateway";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    tianxia-core = {
      url = "github:Tianxia-Core/TianxiaOS";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, tianxia-core, ... }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          ledgerBin = pkgs.writeShellScriptBin "tx-tetraledger" ''
            exec ${pkgs.python3}/bin/python3 ${./src/tx_tetraledger.py} "$@"
          '';
          x402Bin = pkgs.writeShellScriptBin "tx-x402-gateway" ''
            exec ${pkgs.python3}/bin/python3 ${./src/tx_x402_gateway.py} "$@"
          '';
        in {
          default = pkgs.symlinkJoin {
            name = "tetraledger-8.7.0";
            paths = [ ledgerBin x402Bin ];
          };
          tx-tetraledger = ledgerBin;
          tx-x402-gateway = x402Bin;
        }
      );

      nixosModules = {
        default = ./nix/tianxia-x402.nix;
        x402-gateway = ./nix/tianxia-x402.nix;
      };
    };
}
