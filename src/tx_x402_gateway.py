#!/usr/bin/env python3
# ffp: TX-TX-X402-GATEWAY glue python
import logging
# DSS-14 AUTO (Tārā/Bhuvanēśvarī/Dhūmāvatī/Bāgalamukhī/Bhairavī): graceful block
import logging as _tx_logging

_tx_log = _tx_logging.getLogger(__name__)
if not _tx_log.handlers:
    _tx_logging.basicConfig(level=_tx_logging.INFO,
                            format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")


def _tx_env(name: str, default: str = "") -> str:
    try:
        import os as _os
        return _os.environ.get(name) or default
    except Exception as _exc:
        logging.getLogger(__name__).debug(
            "suppressed Exception: %s", _exc)
        # dss14 DHUMAVATI: announce
        logging.getLogger(__name__).debug(
            "suppressed Exception: %s", _exc)
        # dss14 DHUMAVATI: announce
        logging.getLogger(__name__).debug(
            "suppressed Exception: %s", _exc)
        # dss14 DHUMAVATI: announce
        logging.getLogger(__name__).debug(
            "suppressed Exception: %s", _exc)
        # dss14 DHUMAVATI: announce
        logging.getLogger(__name__).debug(
            "suppressed Exception: %s", _exc)
        return default


_TX_BASE = _tx_env("TX_BASE_DIR", "/var/lib/tianxia")


def _tx_halted() -> bool:
    """Bāgalamukhī kill-switch: honor operator stop flags."""
    import os as _os
    return _os.path.exists(_os.path.join(_TX_BASE, "AUTONOMY_PAUSED")) or \
        _os.path.exists(_os.path.join(_TX_BASE, "PROBE_STOP"))


def _tx_capability(required: str = "") -> bool:
    """Bhairavī gate for privileged mutations (token or explicit grant)."""
    import os as _os
    want = required or _tx_env("TX_CAPABILITY_TOKEN")
    return bool(want) and _os.environ.get("TX_CAPABILITY_TOKEN") == want
# DSS-14 AUTO END
# ffp: TX-TX_X402_GATEWAY glue python
"""tx_x402_gateway.py -- payment-gated product gateway (machine-to-machine).

No-human revenue streams for the hub: pay-per-request products over the live
substrate. Internal callers carrying the substrate token bypass payment;
everyone else receives a 402 EFM invoice, pays on Base, and replays the
request with X-TX-HASH for on-chain verification (eth_getTransactionReceipt
+ ERC20 Transfer log to treasury, value >= invoice price). Fail-closed on any
doubt. Settlements append EARNINGS.json receipts and a portfolio ledger row;
the receipt `service` field distinguishes inference / acar / signal.

Endpoints: POST /v1/infer  (body forwarded verbatim to the inference router)
           POST /v1/acar   (runs tx_acar.py --analyze <address>, 120 s cap)
           POST /v1/signal (runs tx_signal_feed.py --query <symbol>, read-only)
           GET  /v1/pay/<invoice_id> (renders 402 terms for a payment link)
Headers:  X-Tianxia-Auth (internal bypass) | X-TX-HASH + X-TX-INVOICE (paid).
State:    db/x402_invoices.sqlite3 (invoices, settlements UNIQUE tx_hash).
Prices:   USD-authoritative. price_usdc = USD micro-units (6 dp, x402 standard,
          e.g. $1.00 -> 1000000) is the quoted denomination and appears in every
          402/pay response as price_usdc + price_usd; price_efm is the USD-pegged
          EFM wei settlement equivalent. TX_X402_PRICE_*_EFM pins an EFM amount
          only when set to a non-legacy value (legacy wei defaults are ignored so
          they cannot silently defeat the USD denomination).
Usage:    tx_x402_gateway.py [--serve] | --selftest | --help
"""
import argparse
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shutil
import tempfile

log = _tx_logging.getLogger("tx_x402_gateway")

BASE = os.environ.get("TX_BASE_DIR") or "/var/lib/tianxia"
DB_PATH = os.path.join(BASE, "db", "x402_invoices.sqlite3")
EARNINGS_PATH = os.path.join(BASE, "docs", "faery_fortress", "EARNINGS.json")
PORTFOLIO_DB = os.path.join(BASE, "db", "portfolio.sqlite3")
TOKEN_PATH = os.path.join(BASE, "secrets", "substrate_auth.token")
HOST = os.environ.get("TX_X402_HOST") or "127.0.0.1"
PORT = int(os.environ.get("TX_X402_PORT") or "9196")
UPSTREAM_URL = os.environ.get("TX_X402_UPSTREAM") or "http://127.0.0.1:9188/v1/infer"
UPSTREAM_TIMEOUT_S = float(os.environ.get("TX_X402_UPSTREAM_TIMEOUT") or "120")
RATE_MAX = int(os.environ.get("TX_X402_RATE_MAX") or "30")
RATE_WINDOW_S = 60.0
MAX_BODY_BYTES = 1024 * 1024
PRICE_EFM_DEFAULT = "1000000000000000"
PRICE_ACAR_EFM_DEFAULT = "50000000000000000"
PRICE_SIGNAL_EFM_DEFAULT = "10000000000000000"
# --- USD-pegged pricing (App.A.4 fix: ~2.4e4x revenue understatement) --------
# BEFORE: prices were EFM-denominated while RGO_CATALOG.md advertised USD labels
#   ("$0.05 per scan", "$0.01 per query"). At the live EFM price recorded in
#   db/efm_pool_state.json (efm_usd = 4.1199e-05, 2026-09-12T17:26:41Z):
#       0.05 EFM * 4.1199e-05 = $0.0000021   vs label $0.05   (x23800)
#       0.01 EFM * 4.1199e-05 = $0.00000041  vs label $0.01   (x24272)
#   The receipt `usd_est` was already honest (live pool price), so the defect
#   was a PRICING-SEMANTICS gap, not an on-chain decimals error: EFM decimals
#   are 18 (eth_call decimals() -> 0x12), so amount_wei/1e18 is correct.
# AFTER: the invoice price is derived from a USD target at invoice time using
#   the live pool price, so realized USD ~= the catalog label:
#       $0.05 / 4.1199e-05 = 1213.62 EFM = 1.2136e21 wei  (x24272 vs 5e16)
# An explicit TX_X402_PRICE_*_EFM still pins an EFM amount (operator override).
PRICE_EFM_USD_DEFAULT = "0.001"
PRICE_ACAR_USD_DEFAULT = "0.05"
PRICE_SIGNAL_USD_DEFAULT = "0.01"
PRICE_USD_DEFAULTS = {"inference": PRICE_EFM_USD_DEFAULT,
                      "acar": PRICE_ACAR_USD_DEFAULT,
                      "signal": PRICE_SIGNAL_USD_DEFAULT}
PRICE_USD_ENVS = {"inference": "TX_X402_PRICE_EFM_USD",
                  "acar": "TX_X402_PRICE_ACAR_USD",
                  "signal": "TX_X402_PRICE_SIGNAL_USD"}
EFM_DECIMALS = 18
# DENOMINATION (EFM-wei -> USD): the x402 standard quotes USD; USDC has 6
# decimals, so $1.00 == 1_000_000 micro-units. This is the authoritative quoted
# amount; EFM wei is only the on-chain settlement equivalent and is derived from
# the same USD target at the live pool price (never a bare wei default).
USD_DECIMALS = 6
TTL_S = int(os.environ.get("TX_X402_TTL_S") or "900")
EFM = "0x87C1a58E452AAAb3F33fB1798b8bB80e5f30D17D"
TREASURY = "0xe7Eef656416eC617Ccb4409a9928b6a3D1557769"
CHAIN = "base"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523baf"
RPC_TIMEOUT_S = float(os.environ.get("TX_X402_RPC_TIMEOUT") or "20")
RPCS = ["https://mainnet.base.org", "https://base.publicnode.com",
        "https://1rpc.io/base", "https://base.drpc.org"]
UA = {"User-Agent": "Tianxia-X402/1.0"}
TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
ACAR_BIN = os.path.join(BASE, "bin", "tx_acar.py")
SIGNAL_BIN = os.path.join(BASE, "bin", "tx_signal_feed.py")
PRODUCT_TIMEOUT_S = float(os.environ.get("TX_X402_PRODUCT_TIMEOUT") or "120")
ACAR_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
SIGNAL_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,31}$")
ROUTES = {"/v1/infer": "inference", "/v1/acar": "acar", "/v1/signal": "signal"}

_rpc_idx = 0
_rate_lock = threading.Lock()
_rate_hits = {}
_token_cache = {"mtime": None, "token": ""}
_price_cache = {"ts": 0.0, "usd": None, "source": "none"}


def _parse_price(raw: str, default: str = PRICE_EFM_DEFAULT,
                 env_name: str = "TX_X402_PRICE_EFM") -> int:
    try:
        price = int(raw)
        if price <= 0:
            raise ValueError("non-positive")
        return price
    except ValueError as exc:
        log.error("bad %s=%r (%s); using %s", env_name, raw, exc, default)
        return int(default)


PRICE_EFM = _parse_price(os.environ.get("TX_X402_PRICE_EFM") or PRICE_EFM_DEFAULT)
PRICE_ACAR_EFM = _parse_price(
    os.environ.get("TX_X402_PRICE_ACAR_EFM") or PRICE_ACAR_EFM_DEFAULT,
    PRICE_ACAR_EFM_DEFAULT, "TX_X402_PRICE_ACAR_EFM")
PRICE_SIGNAL_EFM = _parse_price(
    os.environ.get("TX_X402_PRICE_SIGNAL_EFM") or PRICE_SIGNAL_EFM_DEFAULT,
    PRICE_SIGNAL_EFM_DEFAULT, "TX_X402_PRICE_SIGNAL_EFM")


def _parse_usd(raw: str, default: str, env_name: str) -> float:
    try:
        usd = float(raw)
        if usd <= 0:
            raise ValueError("non-positive")
        return usd
    except (ValueError, TypeError) as exc:
        log.error("bad %s=%r (%s); using %s", env_name, raw, exc, default)
        return float(default)


def _usd_to_wei(usd: float, efm_usd: float) -> int:
    """Ceil(usd / efm_usd * 10**EFM_DECIMALS). Raises on unusable inputs."""
    if usd <= 0 or efm_usd <= 0:
        raise ValueError("usd and efm_usd must be positive")
    return int(math.ceil((usd / efm_usd) * (10 ** EFM_DECIMALS)))


def usd_to_usdc_units(usd: float) -> int:
    """USD -> USDC micro-units (6 dp). Authoritative x402 denomination."""
    if usd <= 0:
        raise ValueError("usd must be positive")
    return int(round(usd * (10 ** USD_DECIMALS)))


def _price_usdc_for(service: str) -> int:
    """USD-denominated quote in USDC micro-units (see usd_to_usdc_units)."""
    return usd_to_usdc_units(_price_usd_for(service))


def _efm_default_for(service: str) -> str:
    if service == "acar":
        return PRICE_ACAR_EFM_DEFAULT
    if service == "signal":
        return PRICE_SIGNAL_EFM_DEFAULT
    return PRICE_EFM_DEFAULT


def _efm_env_for(service: str) -> str:
    return {"acar": "TX_X402_PRICE_ACAR_EFM",
            "signal": "TX_X402_PRICE_SIGNAL_EFM"}.get(service, "TX_X402_PRICE_EFM")


def _efm_pin_for(service: str):
    """Explicit TX_X402_PRICE_*_EFM override, or None when unset.

    The legacy EFM defaults (0.001/0.05/0.01 EFM in wei) pre-date USD pricing,
    but the systemd unit still exports TX_X402_PRICE_EFM=1000000000000000. If
    honored as a pin it silently overwrites the USD-derived amount with the
    understated wei value. Exact legacy defaults are therefore treated as
    'unset'; any other value remains a genuine operator override."""
    raw = os.environ.get(_efm_env_for(service))
    if raw is None:
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return raw
    if val == int(_efm_default_for(service)):
        log.warning("ignoring legacy %s=%s (wei default); USD denomination is authoritative",
                    _efm_env_for(service), raw)
        return None
    return raw


def _price_usd_for(service: str) -> float:
    env = PRICE_USD_ENVS.get(service, "TX_X402_PRICE_EFM_USD")
    default = PRICE_USD_DEFAULTS.get(service, PRICE_EFM_USD_DEFAULT)
    return _parse_usd(os.environ.get(env) or default, default, env)


def _price_math_ok() -> bool:
    """In-file unit assertion (denomination proof).

    Proves the quoted denomination is USD micro-units, NOT wei-scale:
      * $1.00 -> 1_000_000 micro-units (USDC 6 dp, x402 standard), not 1e18
      * $0.05/$0.01 -> 50_000/10_000 micro-units
    and that a USD target converts to an EFM wei settlement amount whose
    realised USD (at the live pool price) round-trips back to the target, and is
    strictly above the legacy understated wei default."""
    if usd_to_usdc_units(1.00) != 1_000_000:
        return False
    if usd_to_usdc_units(0.05) != 50_000 or usd_to_usdc_units(0.01) != 10_000:
        return False
    live = 4.1199e-05
    wei = _usd_to_wei(0.05, live)            # $0.05 target -> EFM wei
    round_trip = (wei / (10 ** EFM_DECIMALS)) * live
    legacy = 5 * 10 ** 16                    # legacy 0.05 EFM wei default
    return wei > legacy and abs(round_trip - 0.05) < 0.005


def _price_for(service: str) -> int:
    """Invoice price in EFM wei. Precedence: explicit EFM pin > USD@live > EFM."""
    pin = _efm_pin_for(service)
    if pin:
        return _parse_price(pin, _efm_default_for(service), _efm_env_for(service))
    efm_usd, _src = _efm_usd()
    if efm_usd > 0:
        try:
            return _usd_to_wei(_price_usd_for(service), efm_usd)
        except (ValueError, OverflowError) as exc:
            log.error("USD->EFM conversion failed for %s (%s); EFM default", service, exc)
    else:
        log.warning("live EFM price unavailable; %s priced at EFM default", service)
    return int(_efm_default_for(service))


class RPCError(RuntimeError):
    """All Base RPC endpoints failed (fail-closed marker)."""


def _auth_token() -> str:
    try:
        mtime = os.path.getmtime(TOKEN_PATH)
    except OSError as exc:
        log.error("auth token unavailable at %s: %s (internal bypass disabled)", TOKEN_PATH, exc)
        return ""
    if _token_cache["mtime"] == mtime:
        return _token_cache["token"]
    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError as exc:
        log.error("auth token unreadable at %s: %s", TOKEN_PATH, exc)
        return ""
    _token_cache["mtime"] = mtime
    _token_cache["token"] = token
    return token


def _rate_ok(ip: str) -> bool:
    now = time.monotonic()
    with _rate_lock:
        hits = _rate_hits.setdefault(ip, deque())
        while hits and (now - hits[0]) > RATE_WINDOW_S:
            hits.popleft()
        if len(hits) >= RATE_MAX:
            return False
        hits.append(now)
        return True


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS invoices
        (invoice_id TEXT PRIMARY KEY, created_ts REAL, expires_ts REAL,
         price_efm TEXT, client_ip TEXT, state TEXT DEFAULT 'open', tx_hash TEXT,
         service TEXT DEFAULT 'inference', price_usdc TEXT DEFAULT '')""")
    cols = {row[1] for row in con.execute("PRAGMA table_info(invoices)")}
    if "service" not in cols:
        con.execute("ALTER TABLE invoices ADD COLUMN service TEXT DEFAULT 'inference'")
    if "price_usdc" not in cols:
        con.execute("ALTER TABLE invoices ADD COLUMN price_usdc TEXT DEFAULT ''")
    con.execute("""CREATE TABLE IF NOT EXISTS settlements
        (tx_hash TEXT PRIMARY KEY, invoice_id TEXT, ts REAL,
         amount_efm TEXT, payer TEXT)""")
    return con


def _create_invoice(client_ip: str, price_efm=None, service: str = "inference",
                    price_usdc=None) -> dict:
    if price_efm is None:
        price_efm = PRICE_EFM
    price_efm = int(price_efm)
    if price_usdc is None:
        price_usdc = _price_usdc_for(service)
    price_usdc = int(price_usdc)
    invoice_id = str(uuid.uuid4())
    now = time.time()
    con = _db()
    try:
        con.execute("INSERT INTO invoices (invoice_id, created_ts, expires_ts, "
                    "price_efm, client_ip, state, tx_hash, service, price_usdc) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (invoice_id, now, now + TTL_S, str(price_efm), client_ip,
                     "open", "", service, str(price_usdc)))
        con.commit()
    finally:
        con.close()
    return {"invoice_id": invoice_id, "created_ts": now, "expires_ts": now + TTL_S,
            "price_efm": str(price_efm), "client_ip": client_ip, "state": "open",
            "tx_hash": "", "service": service, "price_usdc": str(price_usdc)}


def _get_invoice(invoice_id: str):
    if not invoice_id:
        return None
    con = _db()
    try:
        row = con.execute(
            "SELECT invoice_id, created_ts, expires_ts, price_efm, client_ip, state, tx_hash, "
            "COALESCE(service, 'inference'), COALESCE(price_usdc, '') "
            "FROM invoices WHERE invoice_id=?",
            (invoice_id,)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    keys = ["invoice_id", "created_ts", "expires_ts", "price_efm", "client_ip",
            "state", "tx_hash", "service", "price_usdc"]
    return dict(zip(keys, row))


def _latest_open_invoice(client_ip: str, service: str = "inference"):
    con = _db()
    try:
        row = con.execute(
            "SELECT invoice_id FROM invoices WHERE client_ip=? AND state='open' "
            "AND COALESCE(service, 'inference')=? "
            "ORDER BY created_ts DESC LIMIT 1", (client_ip, service)).fetchone()
    finally:
        con.close()
    return _get_invoice(row[0]) if row else None


def _expire_invoice(invoice_id: str):
    con = _db()
    try:
        con.execute("UPDATE invoices SET state='expired' WHERE invoice_id=? AND state='open'",
                    (invoice_id,))
        con.commit()
    finally:
        con.close()


def _tx_replayed(tx_hash: str) -> bool:
    con = _db()
    try:
        return con.execute("SELECT 1 FROM settlements WHERE tx_hash=?",
                           (tx_hash,)).fetchone() is not None
    finally:
        con.close()


def _record_settlement(invoice: dict, tx_hash: str, amount_wei: int, payer: str) -> bool:
    """Atomically consume invoice + tx hash. False => already settled (replay)."""
    con = _db()
    try:
        cur = con.execute("INSERT OR IGNORE INTO settlements (tx_hash, invoice_id, ts, amount_efm, payer) "
                          "VALUES (?,?,?,?,?)",
                          (tx_hash, invoice["invoice_id"], time.time(),
                           str(amount_wei), payer))
        if cur.rowcount == 0:
            con.rollback()
            return False
        cur = con.execute("UPDATE invoices SET state='paid', tx_hash=? "
                          "WHERE invoice_id=? AND state='open'",
                          (tx_hash, invoice["invoice_id"]))
        if cur.rowcount == 0:
            con.rollback()
            return False
        con.commit()
        return True
    finally:
        con.close()


def _rpc(method: str, params: list):
    """Base JSON-RPC with endpoint rotation. Raises RPCError when all fail."""
    global _rpc_idx
    last = None
    for _ in range(len(RPCS)):
        url = RPCS[_rpc_idx % len(RPCS)]
        _rpc_idx += 1
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **UA})
        try:
            with urllib.request.urlopen(req, timeout=RPC_TIMEOUT_S) as resp:
                out = json.load(resp)
            if "result" in out:
                return out["result"]
            last = str(out.get("error"))[:120]
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = str(exc)[:120]
            log.warning("base rpc %s failed (%s); rotating", url, last)
    raise RPCError("all base RPCs failed: " + str(last))


def verify_payment(tx_hash: str, invoice):
    """Fail-closed payment proof: SUCCESS receipt + EFM Transfer to treasury >= price."""
    if not TX_RE.match(tx_hash or ""):
        return False, "bad_tx_hash_format", {}
    if invoice is None:
        return False, "unknown_invoice", {}
    if invoice.get("state") != "open":
        return False, "invoice_" + str(invoice.get("state") or "unknown"), {}
    try:
        expires_ts = float(invoice.get("expires_ts") or 0)
    except (TypeError, ValueError):
        return False, "invoice_bad_expiry", {}
    if time.time() > expires_ts:
        return False, "invoice_expired", {}
    if _tx_replayed(tx_hash):
        return False, "replay", {}
    try:
        price_efm = int(invoice.get("price_efm") or "0")
    except (TypeError, ValueError):
        return False, "invoice_bad_price", {}
    if price_efm <= 0:
        return False, "invoice_bad_price", {}
    try:
        receipt = _rpc("eth_getTransactionReceipt", [tx_hash])
    except RPCError as exc:
        log.error("verification RPC unavailable for %s: %s", tx_hash[:18], exc)
        return False, "rpc_unavailable", {}
    if receipt is None:
        return False, "no_receipt", {}
    try:
        status = int(receipt.get("status", "0x0"), 16)
    except (TypeError, ValueError):
        return False, "bad_receipt_status", {}
    if status != 1:
        return False, "tx_failed", {}
    for entry in receipt.get("logs") or []:
        try:
            if str(entry.get("address", "")).lower() != EFM.lower():
                continue
            topics = entry.get("topics") or []
            if len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
                continue
            if ("0x" + str(topics[2])[-40:]).lower() != TREASURY.lower():
                continue
            value = int(entry.get("data", "0x0"), 16)
        except (TypeError, ValueError) as exc:
            log.warning("skipping malformed transfer log: %s", exc)
            continue
        if value >= price_efm:
            payer = "0x" + str(topics[1])[-40:]
            return True, "ok", {"amount_wei": value, "payer": payer}
    return False, "no_matching_transfer", {}


def _efm_usd():
    """Cached EFM/USD from tx_efm_pool (fallback tx_efm_pay); 0.0 when unavailable."""
    now = time.monotonic()
    if _price_cache["usd"] is not None and (now - _price_cache["ts"]) < 600.0:
        return _price_cache["usd"], _price_cache["source"]
    usd, source = 0.0, "unavailable"
    sys.path.insert(0, os.path.join(BASE, "bin"))
    try:
        import tx_efm_pool
        snap = tx_efm_pool.snapshot()
        px = float(snap.get("efm_usd") or 0.0)
        if px > 0:
            usd, source = px, "tx_efm_pool"
    except Exception as exc:
        log.warning("efm price via tx_efm_pool unavailable: %s", exc)
    if usd <= 0:
        try:
            import tx_efm_pay
            px = float(tx_efm_pay.efm_price_usd() or 0.0)
            if px > 0:
                usd, source = px, "tx_efm_pay"
        except Exception as exc:
            log.warning("efm price via tx_efm_pay unavailable: %s", exc)
    _price_cache["ts"] = now
    _price_cache["usd"] = usd
    _price_cache["source"] = source
    return usd, source


def _earn_append(receipt: dict):
    """Append receipt to EARNINGS.json under an exclusive lock (atomic replace)."""
    os.makedirs(os.path.dirname(EARNINGS_PATH), exist_ok=True)
    lock_path = EARNINGS_PATH + ".lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            doc = {"generated": None, "total_usd_est": 0.0, "receipts": []}
            if os.path.exists(EARNINGS_PATH):
                try:
                    with open(EARNINGS_PATH, "r", encoding="utf-8") as fh:
                        doc = json.load(fh)
                except (OSError, ValueError) as exc:
                    log.error("EARNINGS.json unreadable (%s); quarantining", exc)
                    try:
                        os.replace(EARNINGS_PATH, EARNINGS_PATH + ".corrupt")
                    except OSError as ren_exc:
                        log.error("quarantine failed: %s", ren_exc)
                    doc = {"generated": None, "total_usd_est": 0.0, "receipts": []}
            if not isinstance(doc, dict) or not isinstance(doc.get("receipts"), list):
                log.error("EARNINGS.json schema unexpected; reinitializing")
                doc = {"generated": None, "total_usd_est": 0.0, "receipts": []}
            doc["receipts"].append(receipt)
            doc["total_usd_est"] = round(
                sum(float(r.get("usd_est") or 0.0) for r in doc["receipts"]), 8)
            doc["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            tmp = EARNINGS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=1)
            os.replace(tmp, EARNINGS_PATH)
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _ledger_row(invoice_id: str, tx_hash: str, amount_wei: int, payer: str,
                usd_est: float, price_source: str, service: str = "inference"):
    amount_efm = amount_wei / 1e18
    notes = json.dumps({
        "tx_hash": tx_hash,
        "payer_ref": payer,
        "amount_efm": round(amount_efm, 8),
        "amount_wei": str(amount_wei),
        "efm_usd": _price_cache["usd"],
        "price_source": price_source,
        "service": service,
        "rail": "x402-efm",
    })
    con = sqlite3.connect(PORTFOLIO_DB, timeout=10)
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS rgu_revenue_events (
            event_id TEXT PRIMARY KEY, ts REAL, tenant TEXT, alloc_id TEXT,
            template_id TEXT, kind TEXT, amount_usd REAL, unit TEXT, notes TEXT)""")
        con.execute("INSERT OR IGNORE INTO rgu_revenue_events "
                    "(event_id, ts, tenant, alloc_id, template_id, kind, amount_usd, unit, notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    ("x402-" + invoice_id, time.time(), "tianxia", invoice_id,
                     "x402-gateway", "x402-autonomous", usd_est, "USD", notes))
        con.commit()
    finally:
        con.close()


def settle_and_record(invoice: dict, tx_hash: str, info: dict) -> bool:
    """Consume payment, then emit earnings receipt + portfolio ledger row."""
    amount_wei = int(info.get("amount_wei") or 0)
    payer = str(info.get("payer") or invoice.get("client_ip") or "")
    service = str(invoice.get("service") or "inference")
    if not _record_settlement(invoice, tx_hash, amount_wei, payer):
        log.warning("settlement race/replay for tx %s", tx_hash[:18])
        return False
    efm_usd, price_source = _efm_usd()
    usd_est = round((amount_wei / 1e18) * efm_usd, 8)
    receipt = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rail": "x402-efm",
        "amount_efm": round(amount_wei / 1e18, 8),
        "amount_wei": str(amount_wei),
        "usd_est": usd_est,
        "tx_hash": tx_hash,
        "invoice_id": invoice["invoice_id"],
        "service": service,
        "payer_ref": payer,
    }
    try:
        _earn_append(receipt)
    except Exception as exc:
        log.error("EARNINGS.json append failed: %s", exc)
    try:
        _ledger_row(invoice["invoice_id"], tx_hash, amount_wei, payer, usd_est,
                    price_source, service)
    except Exception as exc:
        log.error("portfolio ledger insert failed: %s", exc)
    log.info("settled x402 invoice=%s service=%s tx=%s amount_wei=%s usd_est=%s source=%s",
             invoice["invoice_id"], service, tx_hash[:18], amount_wei, usd_est, price_source)
    return True


def public_base_url() -> str:
    """Public base for shareable payment links (env TX_X402_PUBLIC_URL)."""
    base = (os.environ.get("TX_X402_PUBLIC_URL") or "").strip()
    if base:
        return base.rstrip("/")
    host = "127.0.0.1" if HOST in ("0.0.0.0", "::") else HOST
    return "http://%s:%d" % (host, PORT)


def payment_link(lead_id: int = 0, usd: float | None = None,
                 service: str = "service", client_ip: str = "outreach") -> dict:
    """Real x402 payment-link builder for the Jev booking step.

    Creates an invoice and returns a shareable URL (GET /v1/pay/<id>) that
    renders the 402 terms. Additive, default-deny safe: creates an invoice row
    only; never moves funds, never sends. Honors the kill-switch."""
    if _tx_halted():
        return {"ok": False, "reason": "kill-switch engaged (AUTONOMY_PAUSED/PROBE_STOP)"}
    if usd is None:
        env = PRICE_USD_ENVS.get(service, "TX_X402_PRICE_EFM_USD")
        usd = _parse_usd(os.environ.get(env) or PRICE_USD_DEFAULTS.get(service, PRICE_EFM_USD_DEFAULT),
                         PRICE_USD_DEFAULTS.get(service, PRICE_EFM_USD_DEFAULT), env)
    efm_usd, src = _efm_usd()
    price = None
    if efm_usd > 0:
        try:
            price = _usd_to_wei(float(usd), efm_usd)
        except (ValueError, OverflowError) as exc:
            log.warning("payment_link USD->EFM failed (%s); EFM default", exc)
    inv = _create_invoice("outreach:%s" % lead_id, price, service)
    base = public_base_url()
    return {"ok": True, "lead_id": lead_id, "invoice_id": inv["invoice_id"],
            "link": "%s/v1/pay/%s" % (base, inv["invoice_id"]),
            "pay_to": TREASURY, "token": EFM, "chain": CHAIN, "memo": inv["invoice_id"],
            "price_usdc": int(inv["price_usdc"]),
            "price_usd": round(int(inv["price_usdc"]) / (10 ** USD_DECIMALS), 6),
            "price_efm": inv["price_efm"], "usd": round(float(usd), 4),
            "price_source": src, "expires_ts": inv["expires_ts"], "service": service}


def _quote_usdc_units(invoice: dict) -> int:
    """Authoritative quoted amount in USDC micro-units (6 dp).

    Prefers the stored invoice denomination; falls back to the USD catalog
    price so legacy rows lacking price_usdc still quote a correct magnitude."""
    service = str(invoice.get("service") or "inference")
    try:
        stored = int(invoice.get("price_usdc") or 0)
    except (TypeError, ValueError):
        stored = 0
    if stored > 0:
        return stored
    return _price_usdc_for(service)


def _payment_required(invoice: dict) -> dict:
    """402 terms. Quoted amount is USD micro-units (x402 standard), NOT wei."""
    service = str(invoice.get("service") or "inference")
    price_usdc = _quote_usdc_units(invoice)
    return {
        "error": "payment_required",
        "invoice_id": invoice["invoice_id"],
        "price_usdc": price_usdc,
        "price_usd": round(price_usdc / (10 ** USD_DECIMALS), 6),
        "price_efm": int(invoice["price_efm"]),
        "pay_to": TREASURY,
        "token": EFM,
        "chain": CHAIN,
        "memo": invoice["invoice_id"],
        "ttl_s": TTL_S,
        "expires_ts": invoice["expires_ts"],
        "service": service,
        "pay_hint": "send EFM on Base to pay_to, then retry with X-TX-HASH and X-TX-INVOICE headers",
    }


def _proxy_upstream(body: bytes):
    """Forward request to the inference router. Returns (status, body_bytes)."""
    req = urllib.request.Request(
        UPSTREAM_URL, data=body,
        headers={"Content-Type": "application/json", "X-Tianxia-Auth": _auth_token()})
    try:
        with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT_S) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code), exc.read()
        except OSError as read_exc:
            log.error("upstream error body unreadable: %s", read_exc)
            return int(exc.code), b'{"status":"UPSTREAM_ERROR"}'
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        log.error("inference upstream unavailable: %s", exc)
        return 502, json.dumps({"status": "BAD_GATEWAY",
                                "error": "inference upstream unavailable: " + str(exc)[:200]}).encode()


def _parse_json_body(body: bytes):
    try:
        payload = json.loads((body or b"{}").decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validate_product_body(service: str, body: bytes):
    """Validate route payloads before an invoice is created. (ok, error)."""
    if service == "inference":
        return True, ""
    payload = _parse_json_body(body)
    if payload is None:
        return False, "body must be a JSON object"
    if service == "acar":
        if not ACAR_ADDR_RE.match(str(payload.get("address") or "").strip()):
            return False, "address must match ^0x[0-9a-fA-F]{40}$"
    elif service == "signal":
        if not SIGNAL_SYMBOL_RE.match(str(payload.get("symbol") or "").strip()):
            return False, "symbol must match ^[A-Za-z0-9][A-Za-z0-9._/-]{0,31}$"
    return True, ""


def _product_command(service: str, body: bytes):
    """Build a list-args argv for the paid product tool (never a shell string)."""
    payload = _parse_json_body(body)
    if payload is None:
        return None
    python = sys.executable or "python3"
    if service == "acar":
        return [python, ACAR_BIN, "--analyze", str(payload.get("address")).strip()]
    if service == "signal":
        return [python, SIGNAL_BIN, "--query", str(payload.get("symbol")).strip().upper()]
    return None


def _json_from_stdout(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        log.debug("DSS-14: non-fatal exception ignored")
    for line in reversed(text.splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _run_product(service: str, body: bytes):
    """Run a paid product tool as a list-args subprocess. Returns (status, bytes)."""
    argv = _product_command(service, body)
    if not argv:
        return 400, json.dumps({"status": "BAD_REQUEST",
                                "error": "body must be a JSON object"}).encode()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=PRODUCT_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        log.error("%s product timed out after %ss", service, PRODUCT_TIMEOUT_S)
        return 504, json.dumps({"status": "TIMEOUT", "service": service,
                                "error": "product exceeded %ss" % PRODUCT_TIMEOUT_S}).encode()
    except OSError as exc:
        log.error("%s product failed to start: %s", service, exc)
        return 502, json.dumps({"status": "BAD_GATEWAY", "service": service,
                                "error": str(exc)[:200]}).encode()
    doc = _json_from_stdout(proc.stdout)
    if doc is None:
        log.error("%s product produced no JSON (rc=%s stderr=%.200s)", service,
                  proc.returncode, (proc.stderr or "").strip())
        return 502, json.dumps({"status": "PRODUCT_ERROR", "service": service,
                                "rc": proc.returncode,
                                "error": "product produced no JSON output"}).encode()
    return 200, json.dumps(doc).encode("utf-8")


def _dispatch_product(service: str, body: bytes):
    """Route a request to its product backend. Returns (status, body_bytes)."""
    if service == "inference":
        return _proxy_upstream(body)
    return _run_product(service, body)


class X402Handler(BaseHTTPRequestHandler):
    server_version = "TianxiaX402/1.0"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send_raw(self, code: int, body: bytes, extra_headers: dict = None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, val in (extra_headers or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, out: dict, extra_headers: dict = None):
        self._send_raw(code, json.dumps(out).encode("utf-8"), extra_headers)

    def _client_ip(self) -> str:
        return str(self.client_address[0]) if self.client_address else "unknown"

    def do_GET(self):
        path = (self.path or "").split("?", 1)[0].rstrip("/") or "/"
        if path.startswith("/v1/pay/"):
            invoice = _get_invoice(path[len("/v1/pay/"):])
            if invoice is None:
                self._send_json(404, {"status": "NOT_FOUND", "error": "unknown invoice"})
                return
            out = _payment_required(invoice)
            out["status"] = "PAY" if invoice.get("state") == "open" else invoice.get("state", "unknown")
            out["invoice_url"] = "%s/v1/pay/%s" % (public_base_url(), invoice["invoice_id"])
            self._send_json(200, out)
            return
        self._send_json(405, {"status": "METHOD_NOT_ALLOWED",
                              "error": "POST /v1/infer, /v1/acar or /v1/signal; GET /v1/pay/<invoice_id>"})

    def do_POST(self):
        ip = self._client_ip()
        if _tx_halted():
            log.warning("kill-switch active; rejecting request from %s", ip)
            self._send_json(503, {"status": "HALTED",
                                  "error": "kill-switch active (AUTONOMY_PAUSED/PROBE_STOP)"})
            return
        if not _rate_ok(ip):
            log.warning("rate limit exceeded for %s", ip)
            self._send_json(429, {"status": "RATE_LIMITED",
                                  "error": "max %d requests/min per IP" % RATE_MAX})
            return
        path = (self.path or "").split("?", 1)[0]
        path = path.rstrip("/") or "/"
        service = ROUTES.get(path)
        if service is None:
            self._send_json(404, {"status": "NOT_FOUND",
                                  "error": "unknown route (POST /v1/infer|/v1/acar|/v1/signal)"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"status": "BAD_REQUEST", "error": "invalid Content-Length"})
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"status": "PAYLOAD_TOO_LARGE",
                                  "error": "body > %d bytes" % MAX_BODY_BYTES})
            return
        body = self.rfile.read(length) if length else b""
        valid, verr = _validate_product_body(service, body)
        if not valid:
            log.warning("bad %s request from %s: %s", service, ip, verr)
            self._send_json(400, {"status": "BAD_REQUEST", "error": verr})
            return
        client_auth = self.headers.get("X-Tianxia-Auth", "") or ""
        token = _auth_token()
        if token and hmac.compare_digest(client_auth, token):
            status, out = _dispatch_product(service, body)
            self._send_raw(status, out)
            return

        tx_hash = (self.headers.get("X-TX-HASH", "") or "").strip()
        if not tx_hash:
            invoice = _create_invoice(ip, _price_for(service), service)
            log.info("402 invoice=%s service=%s price_efm=%s client=%s",
                     invoice["invoice_id"], service, invoice["price_efm"], ip)
            self._send_json(402, _payment_required(invoice))
            return

        invoice_id = (self.headers.get("X-TX-INVOICE", "") or "").strip()
        invoice = _get_invoice(invoice_id) if invoice_id else \
            _latest_open_invoice(ip, service)
        if invoice is None:
            fresh = _create_invoice(ip, _price_for(service), service)
            out = _payment_required(fresh)
            out["error"] = "unknown_invoice"
            out["reason"] = "no open invoice for X-TX-INVOICE/%s" % ip
            self._send_json(402, out)
            return
        if invoice.get("state") == "open" and time.time() > float(invoice["expires_ts"]):
            _expire_invoice(invoice["invoice_id"])
            fresh = _create_invoice(ip, _price_for(service), service)
            out = _payment_required(fresh)
            out["error"] = "invoice_expired"
            out["reason"] = "invoice_expired"
            self._send_json(402, out)
            return

        ok, reason, info = verify_payment(tx_hash, invoice)
        if not ok:
            log.warning("payment unverified (%s) invoice=%s tx=%s client=%s",
                        reason, invoice["invoice_id"], tx_hash[:18], ip)
            out = _payment_required(invoice)
            out["error"] = "payment_unverified"
            out["reason"] = reason
            out["tx_hash"] = tx_hash
            self._send_json(402, out)
            return
        if not settle_and_record(invoice, tx_hash, info):
            out = _payment_required(invoice)
            out["error"] = "payment_unverified"
            out["reason"] = "replay"
            self._send_json(402, out)
            return
        status, out = _dispatch_product(service, body)
        self._send_raw(status, out, {"X-Payment-Settled": tx_hash})


def _selftest() -> int:
    """Mock-receipt end-to-end: 402 -> verified settle -> replay/expiry fail-closed."""
    import shutil
    import tempfile
    import threading as _threading
    import urllib.request as _req
    global DB_PATH, EARNINGS_PATH, PORTFOLIO_DB, PRICE_EFM

    results = []

    def check(name: str, cond: bool, detail: str = ""):
        results.append({"check": name, "ok": bool(cond), "detail": detail})

    tmp = tempfile.mkdtemp(prefix="tx_x402_selftest_")
    DB_PATH = os.path.join(tmp, "x402_invoices.sqlite3")
    EARNINGS_PATH = os.path.join(tmp, "EARNINGS.json")
    PORTFOLIO_DB = os.path.join(tmp, "portfolio.sqlite3")
    PRICE_EFM = _usd_to_wei(0.001, 0.00004)

    good_hash = "0x" + "ab" * 32
    failed_hash = "0x" + "cd" * 32
    wrong_to_hash = "0x" + "ef" * 32
    short_hash = "0x" + "12" * 32
    replay_hash = good_hash
    good_transfer = {
        "address": EFM,
        "topics": [TRANSFER_TOPIC,
                   "0x" + "00" * 12 + "11" * 20,
                   "0x" + "00" * 12 + TREASURY[2:].lower()],
        "data": hex(PRICE_EFM)[2:].zfill(64),
    }
    wrong_to_transfer = dict(good_transfer, topics=[
        TRANSFER_TOPIC, "0x" + "00" * 12 + "11" * 20,
        "0x" + "00" * 12 + "22" * 20])
    short_transfer = dict(good_transfer, data=hex(PRICE_EFM - 1)[2:].zfill(64))
    mock_receipts = {
        good_hash: {"status": "0x1", "logs": [good_transfer]},
        failed_hash: {"status": "0x0", "logs": [good_transfer]},
        wrong_to_hash: {"status": "0x1", "logs": [wrong_to_transfer]},
        short_hash: {"status": "0x1", "logs": [short_transfer]},
    }
    rpc_calls = {"n": 0}

    def mock_rpc(method, params):
        rpc_calls["n"] += 1
        return mock_receipts.get(str(params[0]).lower())

    def mock_proxy(body):
        return 200, json.dumps({"status": "SUCCESS", "model": "mock-forest",
                                "response": "pong", "echo_bytes": len(body)}).encode()

    original = (globals()["_rpc"], globals()["_proxy_upstream"], globals()["_tx_halted"],
                globals()["_efm_usd"])
    globals()["_rpc"] = mock_rpc
    globals()["_proxy_upstream"] = mock_proxy
    globals()["_tx_halted"] = lambda: False
    globals()["_efm_usd"] = lambda: (0.00004, "selftest-fixed")

    server = ThreadingHTTPServer(("127.0.0.1", 0), X402Handler)
    server.daemon_threads = True
    port = server.server_address[1]
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(headers: dict, payload: dict, path: str = "/v1/infer"):
        data = json.dumps(payload).encode()
        request = _req.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                               headers={"Content-Type": "application/json", **headers})
        try:
            with _req.urlopen(request, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode()), dict(exc.headers)

    try:
        code, out, _ = post({}, {"prompt": "ping"})
        check("402_status", code == 402, "code=%s" % code)
        check("402_invoice_uuid", bool(re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            out.get("invoice_id", ""))), out.get("invoice_id", ""))
        check("402_price", out.get("price_efm") == _usd_to_wei(0.001, 0.00004),
              "usd-derived=%s" % out.get("price_efm"))
        check("402_price_usdc_denomination", out.get("price_usdc") == 1000 and
              out.get("price_usd") == 0.001,
              "price_usdc=%s price_usd=%s" % (out.get("price_usdc"), out.get("price_usd")))
        check("usd_micro_unit_assertion", usd_to_usdc_units(1.00) == 1_000_000,
              "1.00 USD -> %s micro-units" % usd_to_usdc_units(1.00))
        check("usd_price_fix", _price_math_ok(),
              "factor=%.0fx" % (_usd_to_wei(0.05, 4.1199e-05) / (5 * 10 ** 16)))
        check("402_pay_to", out.get("pay_to", "").lower() == TREASURY.lower(), out.get("pay_to", ""))
        check("402_token", out.get("token", "").lower() == EFM.lower(), out.get("token", ""))
        check("402_chain", out.get("chain") == "base", str(out.get("chain")))
        check("402_memo", out.get("memo") == out.get("invoice_id"), str(out.get("memo")))
        check("402_ttl", out.get("ttl_s") == TTL_S, str(out.get("ttl_s")))
        invoice_id = out.get("invoice_id", "")

        code, out, _ = post({"X-TX-HASH": "0x" + "99" * 32,
                             "X-TX-INVOICE": invoice_id}, {"prompt": "ping"})
        check("bad_hash_fail_closed", code == 402 and out.get("reason") == "no_receipt",
              "code=%s reason=%s" % (code, out.get("reason")))

        code, out, hdrs = post({"X-TX-HASH": good_hash,
                                "X-TX-INVOICE": invoice_id}, {"prompt": "ping"})
        check("paid_serve_200", code == 200 and out.get("response") == "pong",
              "code=%s body=%s" % (code, str(out)[:120]))
        check("paid_settled_header", hdrs.get("X-Payment-Settled", "").lower() == good_hash,
              str(hdrs.get("X-Payment-Settled")))
        with open(EARNINGS_PATH, "r", encoding="utf-8") as fh:
            earnings = json.load(fh)
        check("earnings_receipt", len(earnings.get("receipts", [])) == 1 and
              earnings["receipts"][0].get("tx_hash") == good_hash and
              earnings["receipts"][0].get("rail") == "x402-efm" and
              earnings["receipts"][0].get("service") == "inference",
              json.dumps(earnings)[:160])
        con = sqlite3.connect(PORTFOLIO_DB)
        try:
            row = con.execute("SELECT kind, amount_usd, unit FROM rgu_revenue_events "
                              "WHERE alloc_id=?", (invoice_id,)).fetchone()
        finally:
            con.close()
        check("ledger_row", row is not None and row[0] == "x402-autonomous" and row[2] == "USD",
              str(row))

        code, out, _ = post({}, {"prompt": "ping"})
        replay_invoice = out.get("invoice_id", "")
        code, out, _ = post({"X-TX-HASH": replay_hash,
                             "X-TX-INVOICE": replay_invoice}, {"prompt": "ping"})
        check("replay_fail_closed", code == 402 and out.get("reason") == "replay",
              "code=%s reason=%s" % (code, out.get("reason")))

        code, out, _ = post({"X-TX-HASH": failed_hash,
                             "X-TX-INVOICE": replay_invoice}, {"prompt": "ping"})
        check("tx_failed_fail_closed", code == 402 and out.get("reason") == "tx_failed",
              "code=%s reason=%s" % (code, out.get("reason")))

        code, out, _ = post({"X-TX-HASH": wrong_to_hash,
                             "X-TX-INVOICE": replay_invoice}, {"prompt": "ping"})
        check("wrong_recipient_fail_closed",
              code == 402 and out.get("reason") == "no_matching_transfer",
              "code=%s reason=%s" % (code, out.get("reason")))

        code, out, _ = post({"X-TX-HASH": short_hash,
                             "X-TX-INVOICE": replay_invoice}, {"prompt": "ping"})
        check("underpay_fail_closed",
              code == 402 and out.get("reason") == "no_matching_transfer",
              "code=%s reason=%s" % (code, out.get("reason")))

        expired = _create_invoice("127.0.0.1")
        con = sqlite3.connect(DB_PATH)
        try:
            con.execute("UPDATE invoices SET expires_ts=? WHERE invoice_id=?",
                        (time.time() - 5, expired["invoice_id"]))
            con.commit()
        finally:
            con.close()
        code, out, _ = post({"X-TX-HASH": "0x" + "77" * 32,
                             "X-TX-INVOICE": expired["invoice_id"]}, {"prompt": "ping"})
        check("expired_fail_closed", code == 402 and out.get("reason") == "invoice_expired",
              "code=%s reason=%s" % (code, out.get("reason")))

        code, out, _ = post({}, {"address": "0x" + "ab" * 20}, path="/v1/acar")
        check("acar_402_status", code == 402, "code=%s" % code)
        check("acar_402_price", out.get("price_efm") == _usd_to_wei(0.05, 0.00004),
              str(out.get("price_efm")))
        check("acar_402_price_usdc", out.get("price_usdc") == 50_000,
              str(out.get("price_usdc")))
        check("acar_402_service", out.get("service") == "acar", str(out.get("service")))
        code, out, _ = post({}, {"symbol": "ETH"}, path="/v1/signal")
        check("signal_402_status", code == 402, "code=%s" % code)
        check("signal_402_price", out.get("price_efm") == _usd_to_wei(0.01, 0.00004),
              str(out.get("price_efm")))
        check("signal_402_price_usdc", out.get("price_usdc") == 10_000,
              str(out.get("price_usdc")))
        check("signal_402_service", out.get("service") == "signal", str(out.get("service")))
        code, out, _ = post({}, {"address": "0xnothex"}, path="/v1/acar")
        check("acar_bad_address_400", code == 400, "code=%s" % code)
        code, out, _ = post({}, {"symbol": "bad symbol!"}, path="/v1/signal")
        check("signal_bad_symbol_400", code == 400, "code=%s" % code)
        code, out, _ = post({}, {"prompt": "ping"}, path="/v1/nope")
        check("unknown_route_404", code == 404, "code=%s" % code)

        _rate_hits.clear()
        allowed = all(_rate_ok("10.9.9.9") for _ in range(RATE_MAX))
        blocked = not _rate_ok("10.9.9.9")
        check("rate_limit", allowed and blocked, "allowed=%s blocked=%s" % (allowed, blocked))

        method_ok = rpc_calls["n"] >= 4
        check("mock_rpc_exercised", method_ok, "calls=%s" % rpc_calls["n"])
    finally:
        server.shutdown()
        server.server_close()
        globals()["_rpc"], globals()["_proxy_upstream"], globals()["_tx_halted"], \
            globals()["_efm_usd"] = original
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in results if not r["ok"]]
    print(json.dumps({"selftest": "PASS" if not failed else "FAIL",
                      "checks": results, "failed": len(failed)}, indent=1))
    return 0 if not failed else 1


def _serve():
    if HOST not in ("127.0.0.1", "::1", "localhost"):
        log.error("refusing non-loopback bind %s (fail-closed)", HOST)
        return 2
    log.info("tx_x402_gateway bind %s:%s price_efm=%s acar_efm=%s signal_efm=%s "
             "upstream=%s halted=%s",
             HOST, PORT, PRICE_EFM, PRICE_ACAR_EFM, PRICE_SIGNAL_EFM, UPSTREAM_URL,
             _tx_halted())
    server = ThreadingHTTPServer((HOST, PORT), X402Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupt; shutting down")
    finally:
        server.server_close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="Tianxia x402 payment-gated inference gateway")
    parser.add_argument("--serve", action="store_true", help="run HTTP gateway (default)")
    parser.add_argument("--selftest", action="store_true", help="mock-receipt fail-closed tests")
    args = parser.parse_args()
    if not _price_math_ok():
        raise RuntimeError("x402 USD price assertion failed: derivation drifted")
    if args.selftest:
        return _selftest()
    return _serve()


if __name__ == "__main__":
    sys.exit(main())
