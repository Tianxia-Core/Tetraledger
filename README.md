<p align="center">
  <img src="./brand-kit/01-logos/lockups-and-social/dual-lockup-rxm-x-tianxiaos.svg" alt="RASA-X-MACHINA · tianxiaOS" width="740"/>
</p>

# Tetraledger

[![Architecture Tier](https://img.shields.io/badge/Architecture-Tier_3_Autonomous_Organism-a855f7)](https://github.com/Tianxia-Core)
[![tianxiaOS Substrate](https://img.shields.io/badge/Substrate-tianxiaOS_v8.7.0-7c5cff)](https://github.com/Tianxia-Core/tianxiaos-releases)
[![Nix Flake Closure](https://img.shields.io/badge/Nix_Flake-inputs.nixpkgs.follows-22d3ee)](#normalized-nix-flake-integration-zero-store-duplication)
[![DSS-14.2 Gate](https://img.shields.io/badge/DSS--14.2-%E2%89%A48_FFPs_Verified-34d399)](#function-feature-pair-ffp-manifest)

> **RASA-X-MACHINA Sovereign Polyglot Systems · Makers of `tianxiaOS`**
> *Entity Candor: **RASA-X-MACHINA** — Dealum Application `#179423` under active Estonian Startup Committee evaluation (§ 100¹ of the Estonian Aliens Act · Proposed entity upon approval: **RASA-X-MACHINA OÜ**, Tallinn, Estonia)*
> **Live Surface:** [ledger.rasaxmachina.com](https://ledger.rasaxmachina.com) · **Press & Brand Kit:** [rasaxmachina.com/press](https://rasaxmachina.com/press) · **Founder:** [rasaxmachina.com/collins](https://rasaxmachina.com/collins) · **Secure WhatsApp Relay:** [rasaxmachina.com/whatsapp](https://rasaxmachina.com/whatsapp)

**Tetraledger** (*Veritas-Rex 4-Way Cryptographic Settlement Engine*) is the **Tier-3 4-Way Cryptographic Settlement & HTTP `402` (`x402`) Micropayment Organism** (`5` FFPs `<= 8` FFPs) of **RASA-X-MACHINA**. Born directly from 10+ years of frontline FinTech multi-chain & fiat ledger reconciliation experience, it enforces **`€0.00` balance discrepancy** across (1) Fiat Merchant Rails (*Stripe*, *Gumroad*), (2) On-Chain Settlement (*Base L2*, *Solana*), (3) Append-Only SQLite WAL Core Ledgers, and (4) Read-Only Open Banking Feeds (*GoCardless*), anchoring every settlement epoch with a verifiable SHA-256 Merkle solvency root.

---

## Frontline-to-Founder Engineering Lineage

Architected by **Collins Takem** — forged from **10+ years on the FinTech incident-triage and ledger-forensics front lines** (*Blockchain.com*, *CoinLedger*, *SQUIRE*) while completing a Dual Major in **Pure Mathematics & Computer Science at SUNY (`4.00 / 4.00` GPA)**, followed by **3+ years** building **`tianxiaOS`** and its self-hosted autonomous compiler harnesses.

---

## Function-Feature Pair (`FFP`) Manifest (`<= 8` FFPs Bounded Law)

| FFP ID | Architectural Fitness Class | Language | Source Artifact & Capability |
| :--- | :--- | :--- | :--- |
| `FFP-TETRALEDGER-CORE` | `chain-tooling` | `Python` | `src/tx_tetraledger.py` — 4-way settlement auditor & SHA-256 Merkle solvency root generator |
| `FFP-STRIPE-RECONCILE` | `chain-tooling` | `Python` | `src/tx_stripe_reconcile.py` — Deterministic fiat payout & webhook event reconciler |
| `FFP-X402-GATEWAY` | `io-edge` | `Python` | `src/tx_x402_gateway.py` — Machine-to-machine HTTP `402 Payment Required` inference & API settlement gateway |
| `FFP-LEDGER-OBS` | `glue` | `Python` | `src/tx_observability.py` — Structured JSONL audit & Prometheus telemetry emitter |
| `FFP-X402-NIX` | `declarative` | `Nix` | `nix/tianxia-x402.nix` — Hardened NixOS systemd service for `:9196` `x402` gateway |

---

## Stratified Wire & Boundary Contract

- **Tier Classification**: **Tier 3 — Autonomous Settlement & FinTech Audit SKU** (`ledger.rasaxmachina.com` / `pay.rasaxmachina.com`).
- **Zero Phantom Revenue Law (`DHUMAVATI` & `KAMALA`)**: Never synthesizes unbacked balances; every receipt maps 1:1 to a cryptographic hash or webhook event ID.

---

## Normalized Nix Flake Integration (Zero `/nix/store` Duplication)

Per the **RASA-X-MACHINA 3-Tier Stratified Flake Standard**, every Tier-2 Enclave and Tier-3 Organism normalizes `nixpkgs` and `tianxia-core` via `inputs.<x>.follows` so microVM closures compile against a single deterministic `/nix/store` hash:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    tianxia-core = {
      url = "github:Tianxia-Core/TianxiaOS";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
}
```

---

## Quickstart & Verification

```bash
python3 -m py_compile src/tx_tetraledger.py src/tx_x402_gateway.py
python3 security/secret_shield.py
```

---

## Security, Press & Governance (Bot-Shielded)

- **RFC 9116 Vulnerability Disclosure**: [`SECURITY.md`](./SECURITY.md) · [trust.rasaxmachina.com](https://trust.rasaxmachina.com)
- **Official Media, PR & Canonical Logos**: [rasaxmachina.com/press](https://rasaxmachina.com/press)
- **Encrypted Founder Dispatch**: [rasaxmachina.com/collins#encrypted-dispatch](https://rasaxmachina.com/collins#encrypted-dispatch) · [rasaxmachina.com/whatsapp](https://rasaxmachina.com/whatsapp)
