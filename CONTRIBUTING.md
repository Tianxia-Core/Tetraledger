# Contributing Under DSS-14.2 & 3-Tier Stratified Flake Law

1. **FFP Header Requirement**: Every source file must declare `# ffp: <ID> <ffp_class> <lang>` (or `// ffp: ...`) on line 1 or line 2.
2. **8-FFP Bounding Law**: Tier-2 Enclaves and Tier-3 Organisms are strictly bounded to `<= 8` Function-Feature Pairs (`FFPs`) per repository.
3. **Nix Closure Deduplication**: Downstream `flake.nix` files must pin `inputs.tianxia-core.inputs.nixpkgs.follows = "nixpkgs"` to guarantee zero `/nix/store` duplication.
4. **Zero-Scraper & Secret Shield**: Every PR must pass `python3 security/secret_shield.py` with zero raw secrets, zero raw phone numbers, and zero plaintext email scraper vectors.
