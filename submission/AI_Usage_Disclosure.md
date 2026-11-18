# AI Usage Disclosure & Collaboration Log

**Applicant:** Aditya Tiwary  
**Role:** AI Engineer — Chaos Engine Labs  
**Project:** Merge Kingdom 2.5 Migration Architecture & Systems Prototype  
**Time Spent:** [Insert approximate hours spent, e.g. ~4.5 hours]

---

## 1. How AI Tools Were Used

In accordance with Section 02 and Section 05 of the assignment brief (*"Evidence beats volume... Use AI, and show us how... You use AI as a real collaborator"*), Antigravity AI was utilized as an engineering partner throughout this project.

The collaboration followed a strict, test-driven engineering discipline:
1. **Fact Extraction & Assignment Ingestion:** Grounding the AI on the exact facts, code snippets, version distributions, and support incident messages from the 5-page assignment PDF.
2. **Architectural Ideation & Policy Formulation:** Evaluating trade-offs between different conversion models (100% conversion, proportional ratio, and Purchased-First Protection).
3. **Drafting Systems & Schema Designs:** Generating initial boilerplate for SQLAlchemy 2.0 async models, Alembic migrations, and Pydantic schemas.
4. **Adversarial Audit & Stress Testing:** Directing the AI to independently audit its own generated codebase, simulate extreme concurrency race conditions, and identify architectural flaws.

---

## 2. What AI Suggestions Were Retained and Why

| Suggestion | Rationale for Retaining |
| :--- | :--- |
| **Monotonic Revision Counters (`revision_id`)** | Eliminating client timestamps as ordering primitives directly addresses the root cause of Incidents 1 and 2. |
| **Semantic 3-Way Merge Protocol** | Enforcing $\text{level} = \max(\text{server.level}, \text{client.level})$ and booster inventory union guarantees that legitimate player progress is never rolled back during offline sync conflicts. |
| **Decoupling Entitlements from Save Files** | Moving `no_ads` into a dedicated, normalized relational table permanently eliminates the vulnerability in Incident 3 where stale client save JSON stripped paid purchases. |
| **Purchased-First Protection (PFP) Policy** | Retained $\text{Gems} = \min(C_{\text{current}}, C_{\text{purchased}})$ because it is mathematically transparent, non-arbitrary, and strictly compliant with the zero-loss rule. |
| **Dual-Mode `/legacy/sync` Adapter** | Retained to support the ~5% of daily players on Android 7 who cannot update, preventing the catastrophic 18% churn associated with forced updates. |

---

## 3. What Suggestions Were Rejected or Modified and Why

| AI Initial Proposal | Human Intervention & Modification | Reason for Rejection / Modification |
| :--- | :--- | :--- |
| **Proportional Coin-to-Gem Ratio Policy** | **Rejected.** Replaced with Purchased-First Protection (PFP). | The AI initially suggested estimating earned coins based on average level rewards and calculating a ratio. This was rejected because Fact 4 states that spending was never audited. Fabricating estimates introduces legal and customer support liability. |
| **Hard Forced-Update Dialog** | **Rejected.** Replaced with non-forced dual-version compatibility. | The AI initially proposed forcing all clients to update to v2.5. This was rejected because Fact 5 explicitly warned that ~5% of DAU are on Android 7 (which cannot update) and the prior forced update caused an 18% player loss. |
| **Full Accounting Multi-Account Double-Entry Ledger** | **Modified.** Simplified to an append-only player ledger with `balance_before` and `balance_after`. | The AI proposed a multi-entity double-entry ledger with complex currency accounts and bank reconciliations. This was trimmed to avoid unnecessary microservice/enterprise bloat for a casual puzzle game. |

---

## 4. Mistakes, Unsupported Claims, and Defects Identified During Review

During the technical audit and stress-testing phase (STEP 3), several critical defects and unsupported claims were uncovered and resolved:

### 1. Defect: Post-Migration Coin Re-Inflation via Legacy Sync
* **The Defect:** In `/legacy/sync`, the code originally executed `wallet.coins_balance = max(wallet.coins_balance, payload.coins)`. If a player migrated to v2.5 (converting coins to gems) and then synced using an old v2.4 client, their pre-migration coins were restored, enabling currency duplication.
* **Correction:** Patched `legacy.py` to check `migration_records`. Migrated players cannot have wallet balances modified by v2.4 sync uploads.

### 2. Defect: Concurrency Double-Spend Vulnerability
* **The Defect:** When testing simultaneous spend requests against the same balance, both requests initially succeeded. The AI assumed `SELECT ... FOR UPDATE` was sufficient; however, on non-PostgreSQL drivers (such as in-memory test databases), dialect-level locks did not serialize reads.
* **Correction:** Implemented **Optimistic Concurrency Control (OCC)** using `lock_version` in `WalletRepository.mutate_balance`. Version collisions now trigger an immediate re-read and balance re-check, properly rejecting the second spend with a 400 error.

### 3. Defect: Concurrent Save Revision Collision
* **The Defect:** Two simultaneous save uploads with identical base revisions generated identical `next_revision` numbers, resulting in an unhandled database `IntegrityError` (500 Internal Server Error).
* **Correction:** Added collision handling in `SaveSyncService.sync_save` to catch constraint collisions, roll back, re-fetch the latest revision, and execute a 3-way semantic merge.

### 4. Defect: Unchecked Level Progression Leaping
* **The Defect:** Because the merge rule used $\max(\text{server.level}, \text{incoming.level})$, a hacked client could submit `level: 99999` and skip the game.
* **Correction:** Added `MAX_ALLOWED_LEVEL_JUMP = 100` progression sanity checks.

### 5. Defect: Level Reward Farming Abuse
* **The Defect:** The `/wallet/earn-coins` endpoint did not verify whether a level completion reward had already been granted.
* **Correction:** Made level rewards strictly idempotent per player per level (`level_reward_{player_id}_lvl_{level}`).

---

## 5. Conversation Logs

Full raw conversation transcripts containing all prompts, tool calls, and model outputs have been preserved directly from the session logs and will be submitted alongside this document.
