# Security Policy & Sovereign Vulnerability Disclosure

## Supported Releases

| Version | Supported | Cryptographic Attestation |
| :--- | :--- | :--- |
| `v8.7.x` / `v2.x` | Yes | Ed25519 (`RELEASE_SIGNING_KEY.pub.pem`) + CycloneDX 1.5 SBOM |
| `< v2.0` | No | Superseded under `KALI` severance policy |

## Bot-Shielded Reporting Channels (RFC 9116)

To protect engineering triage endpoints from automated credential/contact scraping, **RASA-X-MACHINA** enforces zero raw phone numbers and zero plaintext email URIs across all repositories:

1. **Trust & Compliance Center**: [https://trust.rasaxmachina.com](https://trust.rasaxmachina.com)
2. **Encrypted Security Dispatch**: [https://rasaxmachina.com/collins#encrypted-dispatch](https://rasaxmachina.com/collins#encrypted-dispatch)
3. **Authenticated WhatsApp Business Relay**: [https://rasaxmachina.com/whatsapp](https://rasaxmachina.com/whatsapp)
4. **GitHub Private Vulnerability Reporting**: Use the repository **Security → Report a vulnerability** tab.

## Cryptographic Release Key (Ed25519)

```pem
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAEADZgM9cKZl2b59dwXu0jLVbDbcN22pj/6nvOdvTj4I=
-----END PUBLIC KEY-----
```
