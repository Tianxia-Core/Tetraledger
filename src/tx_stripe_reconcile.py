#!/usr/bin/env python3
# ffp: TX-STRIPE-RECONCILE io-edge python
"""
tx_stripe_reconcile.py -- reconcile the local stripe_catalog with Stripe.

Found in practice: the products already existed and were active in Stripe
(Sovereign Cockpit, Sovereign Fortress, RGU Swarm, each with monthly and annual
prices) while the local stripe_catalog table was empty. tx_stripe_sync.sh
decides whether to create a product by reading only that local table, so every
run tried to create objects that already existed and failed with
resource_already_exists.

This reads the real state from Stripe (read-only against the API; the only write
is to the local sqlite) and backfills the rows, so idempotency works again.

The Stripe secret is read from the vault and never logged. If the API returns
no products the run aborts rather than writing an empty catalog.

Env: TX_BASE_DIR, TX_BILL_DB, TX_VAULT_DIR, TX_STRIPE_API.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import pathlib
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("TX_BASE_DIR", "/var/lib/tianxia")
DB = os.environ.get("TX_BILL_DB", os.path.join(BASE, "db", "billing.sqlite3"))
VAULT = os.environ.get("TX_VAULT_DIR", os.path.join(BASE, "secrets"))
API = os.environ.get("TX_STRIPE_API", "https://api.stripe.com/v1")

log = logging.getLogger("tx_stripe_reconcile")

# local slug -> product name as it appears in Stripe
TARGETS = {
    "sovereign-cockpit": "Sovereign Cockpit",
    "sovereign-fortress": "Sovereign Fortress",
    "rgu-swarm": "RGU Swarm",
}


def load_key() -> str:
    """Read the Stripe secret from the vault env file. Never logged."""
    src = pathlib.Path(VAULT) / "stripe.env"
    if not src.is_file():
        raise FileNotFoundError(f"vault file absent: {src}")
    m = re.search(r"STRIPE_SECRET_KEY\s*=\s*(\S+)", src.read_text())
    if not m:
        raise KeyError(f"{src} has no STRIPE_SECRET_KEY")
    return m.group(1)


def get(key: str, path: str, **params) -> dict:
    """GET a Stripe resource. Returns {"error": {...}} rather than raising."""
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    cred = base64.b64encode(key.encode() + b":").decode()
    req.add_header("Authorization", "Basic " + cred)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()[:200].decode("utf-8", "replace")
        return {"error": {"message": f"HTTP {exc.code}: {body}"}}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"error": {"message": f"{type(exc).__name__}: {exc}"}}


def _interval(prices: dict, unit: str) -> str:
    for pr in prices.get("data", []):
        if pr.get("recurring", {}).get("interval") == unit:
            return pr.get("id", "")
    return ""


def reconcile(dry_run: bool = False) -> int:
    key = load_key()
    prods = get(key, "/products", limit=100).get("data", [])
    if not prods:
        log.error("no products returned; refusing to write an empty catalog")
        return 1
    log.info("products visible: %d", len(prods))

    con = sqlite3.connect(DB)
    cur = con.cursor()
    now = int(time.time())
    rows = 0

    for slug, name in TARGETS.items():
        hit = next((p for p in prods if p.get("name") == name), None)
        if not hit:
            log.warning("%-20s NOT FOUND in Stripe", slug)
            continue
        pid = hit["id"]
        prices = get(key, "/prices", product=pid, limit=20)
        if prices.get("error"):
            log.error("%-20s price lookup failed: %s", slug, prices["error"])
            continue
        month = _interval(prices, "month")
        year = _interval(prices, "year")
        if dry_run:
            log.info("[dryrun] %-20s product=%s month=%s year=%s active=%s",
                     slug, pid, month or "-", year or "-", hit.get("active"))
        else:
            cur.execute(
                "insert or replace into stripe_catalog values (?,?,?,?,?)",
                (slug, pid, month, year, now))
        rows += 1

    if dry_run:
        log.info("[dryrun] would reconcile %d rows into %s; nothing written",
                 rows, DB)
    else:
        con.commit()
        con.close()
        log.info("reconciled %d rows into %s", rows, DB)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="reconcile stripe_catalog with Stripe")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing the catalog")
    args = ap.parse_args(argv)
    try:
        return reconcile(args.dry_run)
    except Exception as exc:  # noqa: BLE001 - top-level guard: logged, not raised
        log.exception("reconcile failed: %s", exc)
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    sys.exit(main())
