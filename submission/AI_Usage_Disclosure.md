# AI Usage Disclosure & Collaboration Log

**Applicant:** Aditya Tiwary  
**Role:** AI Engineer — Chaos Engine Labs  
**Project:** Merge Kingdom 2.5 Migration Architecture & Systems Prototype  
**Time Spent:** ~4.5 Hours  

---

## 1. Executive Summary: AI Collaboration Approach

This assignment was approached strictly through the lens of Section 02 of the Chaos Engine Labs assignment brief:
> *"Self-teaching & AI fluency: You use AI as a real collaborator. You give it the facts, you check what it says, and you correct it when it is wrong... Evidence beats volume."*

Rather than relying on unvetted, one-shot code generation, Antigravity AI was treated as an accelerated pair programmer and adversarial red team. Every architectural decision, mathematical formulation, and backend service was grounded in the assignment facts, subjected to forensic human review, and empirically validated through automated tests.

---

## 2. Chronological Collaboration Workflow

### Stage 1: Document Grounding & System Ingestion
* **Human Prompting:** Fed the raw 5-page assignment brief into the context, mandating that the model extract every concrete fact, code snippet, and support incident without hallucinating external mechanics.
* **Collaboration:** Forced the AI to map each support ticket to specific lines in the v2.4 C# `SaveSystem` (`DateTimeOffset.Now.ToUnixTimeSeconds()`, `server.saved_at > Current.saved_at`, and `CloudSync.Upload`).

### Stage 2: Policy Formulation & Economic Trade-Offs
* **Collaboration:** Explored mathematical strategies for converting legacy coins to coins and gems given Fact 4 (missing historical coin spending logs).
* **AI Proposal Evaluated:** The AI initially proposed a **Proportional Ratio Policy**, estimating earned coins based on average level rewards.
* **Human Intervention & Rejection:** Rejected the AI's proposal. Fabricating unrecorded earned coins introduces severe legal and player dispute liability. Instead, directed the model to formalize the **Purchased-First Protection (PFP)** policy ($\text{Gems} = \min(C_{\text{current}}, C_{\text{purchased}})$, $\text{Coins} = C_{\text{current}} - \text{Gems}$), proving that it is the only formula that strictly satisfies the core rule: *"No player may lose progress, or anything that they paid for."*

### Stage 3: Architectural Implementation
* **Collaboration:** Structured a clean Modular Monolith in FastAPI, SQLAlchemy 2.0 (async), and PostgreSQL.
* **Directives:** Enforced strict decoupling of game saves, wallets, and entitlements. Banned the client from ever setting balances directly.

### Stage 4: Adversarial Audit & Chaos Stress Testing
* **Collaboration:** Instructed the AI to execute an independent, zero-trust audit of the codebase, writing 12 additional stress tests covering concurrent updates, double-spending races, clock tampering, and duplicate purchases.
* **Outcome:** Uncovered and fixed **5 critical defects** that naive generation had overlooked.

---

## 3. What AI Suggestions Were Retained and Why

| Retained Component | Engineering Rationale |
| :--- | :--- |
| **Monotonic Revision Counters (`revision_id`)** | Eliminates untrusted client timestamps as ordering primitives, permanently solving the root cause of Incidents 1 and 2. |
| **Semantic 3-Way Merge Engine** | Guarantees $\text{level} = \max(\text{server.level}, \text{client.level})$ and booster inventory union during offline sync conflicts. |
| **Decoupling Entitlements from Save Files** | Moving `no_ads` into a normalized `entitlements` table permanently protects paid purchases from being wiped out by stale save uploads (Incident 3). |
| **Dual-Mode `/legacy/sync` Adapter** | Protects the ~5% of daily players on Android 7 who cannot update, preventing the 18% player churn observed during past forced updates. |
| **Purchased-First Protection (PFP) Formula** | Transparent, non-arbitrary, and provably compliant with the zero-loss business mandate. |

---

## 4. What AI Suggestions Were Rejected or Modified and Why

| Initial AI Proposal | Human Review & Modification | Reason for Rejection / Modification |
| :--- | :--- | :--- |
| **Proportional Coin-to-Gem Ratio** | **REJECTED.** Replaced with Purchased-First Protection (PFP). | Fact 4 explicitly states the server has no record of coin spending. Estimating historical spend creates unacceptable customer support disputes and legal exposure. |
| **Blocking Forced-Update Dialog** | **REJECTED.** Replaced with non-blocking dual-version compatibility. | Fact 5 shows 10% of players are on v2.0–2.1 (~half on Android 7, which cannot update), and the last forced update lost 18% of players. A hard cutoff would destroy DAU. |
| **Enterprise Multi-Entity Accounting Ledger** | **MODIFIED.** Simplified to an append-only player transaction log. | The AI proposed complex chart-of-accounts and balance sheet ledgering. This was simplified to an append-only audit ledger with signed deltas to avoid unnecessary enterprise overhead. |

---

## 5. Critical Defects Discovered & Patched During Review

During the adversarial technical audit (STEP 3), five critical bugs were identified in the generated code and corrected before finalization:

### 1. Defect: Post-Migration Coin Re-Inflation via Legacy Sync
* **The Defect:** In `app/api/v1/legacy.py`, the sync handler executed `wallet.coins_balance = max(wallet.coins_balance, payload.coins)`. If a player migrated to v2.5 (converting coins to gems) and then launched an old v2.4 client, their pre-migration coins were restored, creating an infinite currency duplication exploit.
* **The Fix:** Added an audit check against `migration_records`. Once migrated, legacy uploads are prevented from modifying wallet balances.

### 2. Defect: Concurrency Double-Spend Vulnerability (Dialect Isolation)
* **The Defect:** When testing simultaneous spend requests against the same balance, both requests succeeded in test environments. The AI assumed `SELECT ... FOR UPDATE` was sufficient across all SQL engines; however, non-PostgreSQL drivers (like SQLite test beds) did not serialize reads.
* **The Fix:** Implemented **Optimistic Concurrency Control (OCC)** using `lock_version` in `WalletRepository.mutate_balance`. Version collisions now trigger an immediate transaction rollback, balance re-read, and fund re-check, properly rejecting the second spend with `400 Bad Request`.

### 3. Defect: Concurrent Save Revision Collision
* **The Defect:** When two devices of the same player submitted saves at the exact same millisecond with identical base revisions, both generated the same `next_revision` number, causing an unhandled database `IntegrityError` (500 error).
* **The Fix:** Wrapped revision creation in `SaveSyncService.sync_save` with collision detection. If an `IntegrityError` occurs, the session rolls back, re-reads the committed state, and executes a 3-way semantic merge cleanly.

### 4. Defect: Progression Leaping Anomaly
* **The Defect:** Because the merge rule used $\max(\text{server.level}, \text{incoming.level})$, a hacked client could submit `level: 99999` and bypass the entire game.
* **The Fix:** Added `MAX_ALLOWED_LEVEL_JUMP = 100` progression sanity checks in `SaveSyncService.sync_save`.

### 5. Defect: Level Reward Farming Abuse
* **The Defect:** The `/wallet/earn-coins` endpoint did not verify whether a level completion reward had already been granted.
* **The Fix:** Made level rewards strictly idempotent per player per level (`idempotency_key = f"level_reward_{player_id}_lvl_{level}"`).

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

In compliance with Section 04 of the brief, the complete, unedited transcripts of all AI interactions (including all tool executions, background tasks, and code inspections) are preserved directly from the session logs and included with this submission package.
