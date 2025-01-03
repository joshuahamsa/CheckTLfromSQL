# XRP Ledger Trustline Verification Script
This script is designed to verify whether XRP Ledger (XRPL) wallets have the required trustline set for a specific token. If a wallet does not have the trustline or the trustline status cannot be determined, the script organizes these wallets into separate tables (missing_tl or retry_queue) for further processing.

This README is designed for non-developers with no prior experience in coding or Integrated Development Environments (IDEs). It provides clear instructions for setting up and using the script, as well as basic details about how to modify variables to suit your needs.

## Features
Trustline Verification: Checks if each wallet in a database has the specified trustline.
Automatic Retry: Retries failed requests with exponential backoff.
Failover: Uses multiple XRPL nodes for better reliability.
Organized Output: Outputs wallets without trustlines to a separate table and retries unverified wallets in a second pass.
Logging: Detailed logs for tracking progress and errors.
Prerequisites
Python Installation: Ensure Python 3.8 or later is installed on your computer. Download Python.
SQLite Database: The script assumes a pre-existing SQLite database containing a table with wallet addresses and balances.
Python Libraries: Install the required libraries using the following command:
```bash
pip install xrpl
```
## Setup Instructions
### Step 1: Prepare Your Database
The script requires a SQLite database file (e.g., snapshot.db) with the following structure:

1. **Database File:** The default database file is snapshot.db. You can use any file, but you must update the DB_PATH variable in the script.

2. **Required Table:** The table for wallets must have:
- `Wallet:` The wallet address (text).
- `Balance:` The balance or amount associated with the wallet (real number).

Example SQL to create the required table:

```sql
CREATE TABLE tokens (
    Wallet TEXT PRIMARY KEY,
    Balance REAL NOT NULL
);
```
3. **Missing Trustlines Table:** The script automatically creates the tokens_missing_tl table for wallets missing the trustline.

4. **Retry Queue Table:** The script also creates a retry_queue table for wallets that couldn't be verified during the first pass.

### Step 2: Configure the Script
Open the script in a text editor (e.g., Notepad or VS Code) and customize the following variables based on your needs:

1. **Database File:** Update the DB_PATH variable with the path to your database file:

```python
DB_PATH = "snapshot.db"
```
2. **Table Names:** Update table names if your database uses different names:

```python
AIRDROP_TABLE = "tokens"
MISSING_TL_TABLE = "tokens_missing_tl"
RETRY_QUEUE_TABLE = "retry_queue"
```
3. **Token Details:**
- **Issuer:** Update the ISSUER_OF_TOKEN with the issuer's wallet address for the trustline:
```
ISSUER_OF_TOKEN = "rJ9uU9jKxNcsNQM2CLKUhPxNn8P4xmhDVq"
```
   - **Currency Hex Code:** Update the CURRENCY_HEX with the currency code (in hexadecimal) for your token:
```
CURRENCY_HEX = "4241594E414E4100000000000000000000000000"
```
  - **XRPL Nodes:** Modify the list of XRPL nodes (NODES) if you want to use different or additional nodes:
```
NODES = [
    "https://xrplcluster.com/",
    "https://s2.ripple.com:51234/",
    "https://xrpl.link/",
]
```

### Step 3: Run the Script
To run the script:

Save the file as xrpl_trustline_checker.py.
Open a terminal (Command Prompt, PowerShell, or any terminal).
Navigate to the folder containing the script:
```bash
cd /path/to/script
```
Run the script:
```bash

python check_tl.py
```

## Script Workflow
1. **First Pass:**

- Checks each wallet in the main table (tokens) for the specified trustline.
- Moves wallets without the trustline to the tokens_missing_tl table.
- Adds wallets that couldn't be verified to the retry_queue table.

2. **Second Pass:**

- Rechecks wallets in the retry_queue table.
- If verification fails again, moves them to tokens_missing_tl.

3. **Output:**

- Logs detailed information about the process.
- Outputs wallets without trustlines into tokens_missing_tl.

## Troubleshooting
1. **Error: "No module named xrpl"**

    - Solution: Install the xrpl library using:
```bash
pip install xrpl
```

2. **Error: "Database file not found"**

    - Solution: Ensure the database file specified in DB_PATH exists. If not, create a new SQLite database.

3. **Unexpected Results:**

    - Check if the database table names and column headers match those in the script.
    - Verify the issuer address and currency hex code.

## Customization Options
1. **Change Database or Table Names:**

    - Update `DB_PATH` and the table names (`AIRDROP_TABLE`, `MISSING_TL_TABLE`, `RETRY_QUEUE_TABLE`) in the script.

2. **Adjust Retry Settings:**

    - Modify the `max_retries_per_nod`e or `base_backoff_seconds` in the `fetch_trustlines_with_failover` function.

3. **Add More Nodes:**

    - Add additional XRPL nodes to the NODES list.

## Example Logs
Below is a sample output log when running the script:

```less
2025-01-02 10:00:00 [INFO] === First Pass: Checking Wallets in airdrop table ===
2025-01-02 10:00:01 [INFO] [rExampleWallet1] Trustline found. Skipping.
2025-01-02 10:00:02 [WARNING] [rExampleWallet2] Could not fetch trustlines. Retrying...
2025-01-02 10:00:05 [INFO] [rExampleWallet2] No trustline found. Moving to tokens_missing_tl.
2025-01-02 10:00:10 [INFO] === Second Pass: Re-checking Wallets in retry_queue ===
2025-01-02 10:00:12 [INFO] [rExampleWallet3] Trustline found. Removing from retry_queue.
2025-01-02 10:00:15 [INFO] All done.
```
## Support
If you encounter issues or have questions, feel free to open a GitHub issue or contact the script author.
