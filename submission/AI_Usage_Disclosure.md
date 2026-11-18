# AI Usage Disclosure & Collaboration Log

**Applicant:** Aditya Tiwary  
**Role:** AI Engineer — Chaos Engine Labs  
**Project:** Merge Kingdom 2.5 Migration Architecture & Systems Prototype  
**Time Spent:** ~4.5 Hours  

---

## 1. Collaboration Methodology

In accordance with Section 02 and Section 05 of the assignment brief (*"Evidence beats volume... Use AI, and show us how"*), Antigravity AI was used as an accelerated engineering collaborator and adversarial red team.

The workflow followed four structured phases:
1. **Fact Ingestion & Grounding:** Fed the 5-page assignment brief into context. Required the AI to cite exact facts, code snippets, and support tickets without external assumptions.
2. **Policy Formulation & Trade-Offs:** Explored conversion models under missing coin spending history (Fact 4). Directed the AI to discard unrecorded estimates and formalize the Purchased-First Protection (PFP) policy.
3. **Architecture & Service Implementation:** Generated FastAPI, SQLAlchemy 2.0 async models, and Alembic migrations under strict separation of concerns (saves, wallets, entitlements).
4. **Adversarial Audit & Stress Testing:** Mandated an independent, zero-trust audit that implemented and executed 28 automated stress tests, uncovering and patching **8 critical integrity and security defects**.

---

## 2. What AI Suggestions Were Retained and Why

| Retained Component | Engineering Rationale |
| :--- | :--- |
| **Monotonic Revisions (`revision_id`)** | Eliminates phone timestamps as ordering primitives, permanently solving Incidents 1 and 2. |
| **Semantic 3-Way Merge** | Enforces `Level = max(Server_Level, Client_Level)` while using operation-based delta reconciliation for consumable inventories to prevent item duplication. |
| **Decoupled Entitlements** | Normalizes `no_ads` into a dedicated table, preventing stale client save JSON from stripping paid purchases (Incident 3). |
| **Dual-Mode `/legacy/sync` Adapter** | Protects the ~5% of daily players on Android 7 who cannot update, preventing the 18% churn of forced updates. |
| **Purchased-First Protection Formula** | `Gems = min(Current_Coins, Lifetime_Purchased_Coins)` provides complete protection for paid currency without arbitrary estimation. |

---

## 3. What AI Suggestions Were Rejected or Modified and Why

| Initial AI Proposal | Human Review & Action | Rationale |
| :--- | :--- | :--- |
| **Proportional Coin-to-Gem Ratio** | **REJECTED.** Replaced with Purchased-First Protection (PFP). | Fact 4 states that coin spending was never logged. Fabricating earned coin estimates creates severe legal and customer dispute exposure. |
| **Blocking Forced-Update Dialog** | **REJECTED.** Replaced with non-blocking dual-version compatibility. | Fact 5 shows 10% of players are on v2.0–2.1 (~half on Android 7, which cannot update), and the prior forced update lost 18% of players. A hard cutoff destroys DAU. |
| **Enterprise Accounting Multi-Account Ledger** | **MODIFIED.** Simplified to an append-only player transaction log. | Trimmed excessive enterprise balance-sheet machinery to maintain a lightweight, maintainable monolithic service. |
| **Client-Supplied Migration Balance** | **REJECTED.** Enforced server-authoritative save snapshot. | Accepting client-supplied legacy coins invites trivial balance inflation attacks. |
| **Naive Inventory `max()` Union** | **MODIFIED.** Replaced with base-save delta reconciliation. | Taking `max()` across devices allowed offline devices to duplicate spent boosters. |
| **Arbitrary Multiplier (`price_cents * 10`)** | **REJECTED.** Replaced with explicit `HISTORICAL_COIN_PACK_CATALOG`. | Prevents miscounting gem packs and No Ads purchases as historical coin purchases. |

---

## 4. Critical Defects Discovered & Patched During Review

During the adversarial technical audit and code review, eight critical defects and design assumptions were caught and patched:

1. **Client-Supplied Migration Balance Inflation (`migration_service.py`):**
   * *Defect:* Migration initially accepted an optional `legacy_coins` payload from the client, allowing tampered clients to inflate gem grants.
   * *Fix:* Removed client overrides; migration calculates balances strictly from the server-authoritative save snapshot.
2. **Inaccurate Historical Coin Calculation (`migration_service.py`):**
   * *Defect:* Multiplied all historical transaction prices by a flat multiplier (`price_cents * 10`), erroneously including gem packs and No Ads purchases.
   * *Fix:* Defined `HISTORICAL_COIN_PACK_CATALOG` with verified quantities per coin SKU, strictly excluding non-coin purchases.
3. **Forged Legacy No Ads Entitlement (`legacy.py`):**
   * *Defect:* Legacy sync granted permanent `no_ads` based purely on client payload `payload.no_ads = True`.
   * *Fix:* Required verified historical server purchase records before granting entitlement; unbacked flags are ignored.
4. **Unauthorized Legacy Sync (`legacy.py`):**
   * *Defect:* Old clients could sync arbitrary saves by supplying any `player_id`.
   * *Fix:* Required `X-Device-Id` header and verified device-to-player registration, rejecting unbound callers with 403 Forbidden.
5. **Consumable Booster Duplication (`save_sync_service.py`):**
   * *Defect:* Inventory union via `max()` restored spent boosters when a stale device reconnected.
   * *Fix:* Implemented operation-based delta reconciliation against `base_save`. Offline consumption is preserved.
6. **Double-Spend Concurrency Vulnerability (`wallet_repo.py`):**
   * *Defect:* Concurrent spend requests against the same balance both succeeded on non-PostgreSQL drivers because `SELECT ... FOR UPDATE` did not serialize reads.
   * *Fix:* Implemented Optimistic Concurrency Control (OCC) checking `lock_version`, rejecting racing transactions with 400 Bad Request.
7. **Concurrent Save Revision Collisions (`save_sync_service.py`):**
   * *Defect:* Simultaneous save uploads generated identical revision IDs, causing an unhandled 500 error.
   * *Fix:* Added conflict detection with rollback, fresh revision fetching, and 3-way semantic merge.
8. **Progression Leaping and Level Reward Tampering (`save_sync_service.py`, `wallet_service.py`):**
   * *Defect:* Clients could submit arbitrary level jumps and farm completion rewards.
   * *Fix:* Added progression sanity checks (`MAX_ALLOWED_LEVEL_JUMP = 100`) and enforced deterministic, idempotent level reward keys based on server reward schedules.

---

## 5. Actual Test Verification Results

All 28 automated test suites were executed against the hardened prototype:
* **Total Automated Tests:** 28/28 Passed (100% pass rate in 2.35s)
* **Code Coverage:** **95% branch coverage** across `backend/app/` (996 statements, 52 missed)
* **Coverage Highlights:** Models (100%), Schemas (100%), Save Sync Service (96%), Wallet Service (100%), Migration Service (92%), Purchase Service (93%), Legacy Adapter (89%).

---

## 6. Time Spent Breakdown

| Activity | Approximate Duration |
| :--- | :--- |
| Problem Decomposition, Fact Extraction & PDF Investigation | ~45 Minutes |
| Architecture, Data Modeling & Migration Policy Formulation | ~60 Minutes |
| Backend Prototype Implementation (FastAPI, Models, Services, APIs) | ~60 Minutes |
| Adversarial Technical Audit, Concurrency Testing & Defect Patching | ~60 Minutes |
| Final Written Assignment & AI Usage Documentation | ~45 Minutes |
| **Total Time Invested** | **~4.5 Hours** |

---

## 7. Raw Conversation Logs

*Note for Reviewers:* Full raw conversation transcripts detailing all interactive prompts, tool invocations, code diffs, and intermediate outputs have been preserved directly from the session logs and are submitted as separate transcript files alongside this repository.
