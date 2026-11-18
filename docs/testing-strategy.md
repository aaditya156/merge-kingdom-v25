# Merge Kingdom 2.5 — Comprehensive Testing Strategy

## 1. Testing Philosophy & Verification Framework

To guarantee absolute compliance with the business mandate:
> **"No player may lose progress, or anything that they paid for."**

Merge Kingdom 2.5 implements a multi-tiered automated verification matrix using **Pytest**, **HTTPX**, and **Asyncio**.

```
             ┌────────────────────────┐
             │   Chaos & E2E Tests    │  (Multi-device sync, incident replication)
             ├────────────────────────┤
             │   Concurrency Tests    │  (Row locking, parallel double-spend, race conditions)
             ├────────────────────────┤
             │   Integration Tests    │  (REST API, DB migrations, purchase verification)
             ├────────────────────────┤
             │      Unit Tests        │  (PFP migration math, merge rules, JWT, hashing)
             └────────────────────────┘
```

---

## 2. Test Suites Matrix & Risk Coverage

| Test ID | Test Category | Target Failure Mode / Requirement | Validation Mechanism |
| :--- | :--- | :--- | :--- |
| **TS-01** | **Support Incident 1** | Tablet vs. phone offline play race condition. | Simulate Device A reaching level 160; Device B offline reaching level 151. Reconnect Device B. Verify Level 160 is preserved. |
| **TS-02** | **Support Incident 2** | Device clock manipulation (tomorrow -> today). | Client sends future `saved_at`. Client later plays offline with real clock. Server rejects clock spoofing; preserves valid offline level progression. |
| **TS-03** | **Support Incident 3** | Loss of "No Ads" entitlement from old tablet sync. | Player buys No Ads on phone. Inactive tablet uploads old save without No Ads. Verify No Ads remains active on both devices. |
| **TS-04** | **Currency Concurrency** | Double-spending and parallel balance race conditions. | 20 parallel HTTP requests attempting to spend 100 gems with total balance of 100 gems. Exactly 1 request succeeds; 19 fail with 400. |
| **TS-05** | **Idempotency** | Duplicate purchase verifications & retries. | Repeat same `POST /purchases/verify` with identical `store_transaction_id` 5 times. Exactly 1 ledger credit; subsequent calls return cached receipt. |
| **TS-06** | **Migration Safety** | Idempotent migration execution and re-runs. | Execute `POST /migration/migrate` twice for Player A. First call converts coins/gems; second call returns 200 without modifying balances. |
| **TS-07** | **PFP Math Edge Cases** | Zero purchases, high balance, whale with low balance. | Unit test PFP algorithm against all persona profiles ($C_{\text{purchased}} = 0, C_{\text{current}} < C_{\text{purchased}}$, etc.). |
| **TS-08** | **Backward Compatibility** | Legacy v2.0–v2.4 client upload via `/legacy/sync`. | Legacy client sends old payload. Server updates progression, protects entitlements, returns legacy JSON structure. |
| **TS-09** | **Transaction Rollback** | Database failure mid-operation. | Force error during ledger entry insertion; verify wallet balance rollback to prevent orphaned ledger records. |
| **TS-10** | **Android 7 Cohort** | Backward compatibility for non-updatable Android 7 devices. | Verify headers and payloads from Android 7 / v2.1 clients function normally without forced-update rejection. |

---

## 3. Detailed Test Scenarios & Assertions

### TS-01: Incident 1 Replication (The Airplane Mode Conflict)
* **Setup:**
  * Player `p_1001` starts at Level 150 on both Tablet (Device A) and Phone (Device B).
* **Execution:**
  1. Tablet plays online to Level 160. Calls `POST /saves/sync` with `level: 160`. Server revision advances to `rev: 2`.
  2. Phone plays in airplane mode to Level 151 with local wall-clock timestamp after Tablet.
  3. Phone reconnects and calls `POST /saves/sync` with `base_revision_id: 1, level: 151`.
* **Assertion:**
  * Server detects conflict (`base_revision_id < current_revision_id`).
  * Semantic merge executes: `level = max(160, 151) = 160`.
  * Response returns `level: 160`. Player progress is never rolled back to 151.

---

### TS-02: Incident 2 Replication (Clock Fast-Forward & Rewind)
* **Setup:**
  * Player `p_1002` at Level 50.
* **Execution:**
  1. Client sets clock forward 24 hours (`T_future = Now + 86400s`) and sends save upload.
  2. Server saves record, recording `client_saved_at = T_future`, but sets authoritative `server_saved_at = T_now` and increments `revision_id: 10`.
  3. Client sets clock back to actual time (`T_real`). Plays 5 levels offline.
  4. Client reconnects and uploads save with `client_saved_at = T_real` and `level: 55`.
* **Assertion:**
  * Under v2.4, this save was rejected because `T_real < T_future`.
  * Under v2.5, server uses `revision_id` and progression validation, NOT client timestamps.
  * Level 55 is accepted and saved.

---

### TS-03: Incident 3 Replication (No Ads Entitlement Preservation)
* **Setup:**
  * Player `p_1003` has two registered devices: Phone and Tablet.
* **Execution:**
  1. Phone purchases "No Ads". Calls `POST /purchases/verify`.
  2. Server creates record in `entitlements` table with `is_active: true`.
  3. Tablet (offline since last year, holding `no_ads: false` in local JSON) boots up and uploads save.
* **Assertion:**
  * Server does not allow save uploads to mutate entitlements.
  * Server returns `entitlements: {"no_ads": true}` in sync response.
  * Tablet updates local state to `no_ads: true`. No Ads is permanently preserved.

---

### TS-04: High-Concurrency Double-Spending Test
* **Setup:**
  * Player `p_1004` has a wallet balance of exactly 100 Gems.
* **Execution:**
  * Dispatch 20 concurrent HTTP requests (`asyncio.gather`) to `POST /wallet/spend` for an item costing 100 Gems, each with unique idempotency keys.
* **Assertion:**
  * Due to PostgreSQL `SELECT ... FOR UPDATE` row locking, exactly **1 request** receives `200 OK`.
  * **19 requests** receive `400 Bad Request` (`INSUFFICIENT_FUNDS`).
  * Final wallet balance is strictly **0 Gems**, never negative.
  * Transaction ledger contains exactly 1 debit entry.

---

### TS-05: Purchase Verification Idempotency Test
* **Setup:**
  * Store transaction `GPA.9999-0000-1111-2222`.
* **Execution:**
  * Client sends 5 identical `POST /purchases/verify` requests simultaneously.
* **Assertion:**
  * Exactly 1 `purchase_records` entry is created.
  * Exactly 1 `currency_transactions` credit entry is generated.
  * Player wallet receives the gem grant exactly once.
  * All 5 requests return `200 OK` with the same confirmation payload.

---

### TS-06: Repeated Migration Idempotency Test
* **Setup:**
  * Player `p_1006` with 5,000 legacy coins and 2,000 lifetime purchased coins.
* **Execution:**
  1. Call `POST /migration/migrate`. Result: 2,000 gems, 3,000 coins.
  2. Call `POST /migration/migrate` immediately again.
  3. Call `POST /migration/migrate` from a second device.
* **Assertion:**
  * Subsequent calls return `200 OK` with status `COMPLETED` and original conversion summary.
  * Wallets table is not modified again.
  * Total gems balance remains 2,000; total coins balance remains 3,000.

---

## 4. Test Execution & Automation Plan

### Test Run Commands
```bash
# Run complete test suite with coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Run concurrency and race condition tests
pytest tests/test_concurrency.py -v -s

# Run incident replication chaos tests
pytest tests/test_incidents.py -v
```

### Continuous Integration (CI) Quality Gates
* **Code Coverage:** Minimum 90% branch coverage across `app/modules/`.
* **Static Analysis:** Strict typing via `mypy`, linting via `ruff`.
* **Zero Race Conditions:** Concurrency tests must pass with 0 failures under heavy parallel load.
