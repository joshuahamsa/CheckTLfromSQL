import sqlite3
import logging
import time
from typing import Optional
from xrpl.clients import JsonRpcClient
from xrpl.models.requests import AccountLines

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
DB_PATH = "snapshot.db"
AIRDROP_TABLE = "tokens"
MISSING_TL_TABLE = "tokens_missing_tl"
RETRY_QUEUE_TABLE = "retry_queue"  # We'll create a separate table for Wallets we can't confirm

# Multiple nodes for failover:
NODES = [
    "https://xrplcluster.com/",
    "https://s2.ripple.com:51234/",
    "https://xrpl.link/",
]

ISSUER_OF_TOKEN = "rJ9uU9jKxNcsNQM2CLKUhPxNn8P4xmhDVq"
CURRENCY_HEX = "4241594E414E4100000000000000000000000000"

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


# ---------------------------------------------------------------------
# Schema Setup
# ---------------------------------------------------------------------
def ensure_tables(conn):
    """
    Ensures that the missing_tl and retry_queue tables exist.
    """
    cursor = conn.cursor()
    
    # missing_tl
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {MISSING_TL_TABLE} (
            Wallet TEXT PRIMARY KEY,
            Balance REAL NOT NULL
        )
    """)
    
    # retry_queue
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {RETRY_QUEUE_TABLE} (
            Wallet TEXT PRIMARY KEY,
            Balance REAL NOT NULL,
            tries INTEGER DEFAULT 0  -- how many times we've retried this Wallet
        )
    """)

    conn.commit()


# ---------------------------------------------------------------------
# XRPL Trustline Fetcher with Failover + Retries
# ---------------------------------------------------------------------
def fetch_trustlines_with_failover(Wallet: str) -> Optional[list]:
    """
    Attempts to fetch trustlines for `Wallet` using multiple nodes (NODES).
    Each node is tried up to 'max_retries_per_node' times with exponential backoff.

    Returns:
        - A list of trustlines if successful.
        - None if ALL nodes fail (i.e., we cannot fetch trustlines at all).
    """

    max_retries_per_node = 2
    base_backoff_seconds = 2

    req = AccountLines(account=Wallet, ledger_index="validated")

    for node_url in NODES:
        client = JsonRpcClient(node_url)
        logging.info(f"[{Wallet}] Trying node: {node_url}")

        # Retry loop for the current node
        for attempt in range(1, max_retries_per_node + 1):
            try:
                response = client.request(req)
                
                if response.is_successful():
                    lines = response.result.get("lines", [])
                    return lines  # Return immediately if successful
                else:
                    logging.warning(
                        f"[{Wallet}] Attempt {attempt}/{max_retries_per_node} at {node_url} "
                        "not successful. Retrying..."
                    )
            except Exception as e:
                logging.error(
                    f"[{Wallet}] Attempt {attempt}/{max_retries_per_node} at {node_url} "
                    f"raised an exception: {e} -- Retrying..."
                )
            
            # Exponential backoff before next attempt on the same node
            time.sleep(base_backoff_seconds * attempt)

        # If we reach here, we have exhausted all attempts on this node
        logging.warning(f"[{Wallet}] Node {node_url} failed all {max_retries_per_node} attempts. Trying next node...")

    # If we exhaust all nodes, we return None => can't fetch trustlines
    logging.error(f"[{Wallet}] All nodes failed to return trustlines.")
    return None


def has_trustline(Wallet: str) -> Optional[bool]:
    """
    Fetches trustlines for the given Wallet using multiple nodes + retries.
    
    Returns:
        True  => The trustline (ISSUER_OF_TOKEN / CURRENCY_HEX) definitely exists
        False => The trustline definitely does NOT exist
        None  => Could not determine (all node requests failed)
    """
    lines = fetch_trustlines_with_failover(Wallet)
    
    if lines is None:
        # Means all requests failed => we do NOT know
        return None

    # If we got lines, check whether our currency & issuer are present
    for line in lines:
        if (line.get("account") == ISSUER_OF_TOKEN and
                line.get("currency") == CURRENCY_HEX):
            return True
    return False


# ---------------------------------------------------------------------
# Processing logic
# ---------------------------------------------------------------------
def process_Wallets_table(conn, table_name: str, second_pass=False):
    """
    1) Reads (Wallet, Balance) from `table_name`.
    2) For each Wallet:
       - Check trustline (with fallback & retries).
       - If `True`, do nothing (they have the trustline).
       - If `False`, move them to missing_tl and remove them from `table_name`.
       - If `None`, means can't determine => if second_pass, treat as no trustline,
         otherwise move them to `retry_queue`.
    3) Returns how many Wallets were moved to missing_tl or retry_queue.
    """
    cursor = conn.cursor()
    rows = cursor.execute(f"SELECT Wallet, Balance FROM {table_name}").fetchall()

    Wallets_moved_missing = 0
    Wallets_moved_retry = 0

    for (Wallet, Balance) in rows:
        tl_status = has_trustline(Wallet)
        time.sleep(0.2)  # Short delay to avoid rapid-fire requests (helps with rate-limiting)

        if tl_status is True:
            # The Wallet definitely has the trustline, so do nothing
            continue

        elif tl_status is False:
            # Definitely no trustline. Move to missing_tl
            logging.info(f"[{Wallet}] No trustline found. Moving to {MISSING_TL_TABLE}.")
            cursor.execute(f"""
                INSERT OR REPLACE INTO {MISSING_TL_TABLE} (Wallet, Balance)
                VALUES (?, ?)
            """, (Wallet, Balance))
            cursor.execute(f"DELETE FROM {table_name} WHERE Wallet = ?", (Wallet,))
            Wallets_moved_missing += 1

        else:
            # tl_status is None => we couldn't determine (all requests failed)
            if second_pass:
                # On second pass, if we STILL can't fetch, treat as no trustline
                logging.info(f"[{Wallet}] Could not confirm trustline on second pass. Moving to {MISSING_TL_TABLE}.")
                cursor.execute(f"""
                    INSERT OR REPLACE INTO {MISSING_TL_TABLE} (Wallet, Balance)
                    VALUES (?, ?)
                """, (Wallet, Balance))
                cursor.execute(f"DELETE FROM {table_name} WHERE Wallet = ?", (Wallet,))
                Wallets_moved_missing += 1
            else:
                # Not second pass => place in retry_queue
                logging.warning(f"[{Wallet}] Could not fetch trustlines, adding to {RETRY_QUEUE_TABLE}.")
                cursor.execute(f"""
                    INSERT OR REPLACE INTO {RETRY_QUEUE_TABLE} (Wallet, Balance, tries)
                    VALUES (?, ?, COALESCE((SELECT tries FROM {RETRY_QUEUE_TABLE} WHERE Wallet=?), 0))
                """, (Wallet, Balance, Wallet))
                cursor.execute(f"DELETE FROM {table_name} WHERE Wallet = ?", (Wallet,))
                Wallets_moved_retry += 1

    conn.commit()
    return Wallets_moved_missing, Wallets_moved_retry


def process_retry_queue(conn):
    """
    Process the Wallets in retry_queue exactly once more (second pass).
    If still no success, move them to missing_tl.
    """
    cursor = conn.cursor()
    rows = cursor.execute(f"SELECT Wallet, Balance, tries FROM {RETRY_QUEUE_TABLE}").fetchall()

    Wallets_moved_missing = 0

    for (Wallet, Balance, tries) in rows:
        tl_status = has_trustline(Wallet)
        time.sleep(0.2)  # short delay to help avoid rate-limiting

        if tl_status is True:
            # Now we see the trustline! Just remove from retry_queue.
            logging.info(f"[{Wallet}] Found trustline on retry pass. Removing from retry_queue.")
            cursor.execute(f"DELETE FROM {RETRY_QUEUE_TABLE} WHERE Wallet = ?", (Wallet,))
            # Nothing else needed
        elif tl_status is False or tl_status is None:
            # If still no trustline or we still can't fetch, move to missing_tl
            logging.info(f"[{Wallet}] No trustline found or still cannot fetch. Moving to missing_tl.")
            cursor.execute(f"""
                INSERT OR REPLACE INTO {MISSING_TL_TABLE} (Wallet, Balance)
                VALUES (?, ?)
            """, (Wallet, Balance))
            cursor.execute(f"DELETE FROM {RETRY_QUEUE_TABLE} WHERE Wallet = ?", (Wallet,))
            Wallets_moved_missing += 1

    conn.commit()
    return Wallets_moved_missing


# ---------------------------------------------------------------------
# Main Script
# ---------------------------------------------------------------------
def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_tables(conn)

    # 1) First pass: process Wallets in the airdrop table
    logging.info("=== First Pass: Checking Wallets in airdrop table ===")
    moved_missing, moved_retry = process_Wallets_table(conn, AIRDROP_TABLE, second_pass=False)
    logging.info(f"First pass complete. Moved {moved_missing} Wallets to missing_tl, "
                 f"{moved_retry} Wallets to retry_queue.")

    # 2) Second pass: Wallets in the retry_queue
    if moved_retry > 0:
        logging.info("=== Second Pass: Re-checking Wallets in retry_queue ===")
        moved_missing_2 = process_retry_queue(conn)
        logging.info(f"Second pass complete. Moved {moved_missing_2} Wallets to missing_tl.")

    # 3) Cleanup / Summary
    conn.close()
    logging.info("All done.")


if __name__ == "__main__":
    main()
