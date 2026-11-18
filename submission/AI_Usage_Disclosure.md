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
4. **Adversarial Audit & Stress Testing:** Mandated an independent, zero-trust audit that wrote 12 automated stress tests, uncovering and patching **5 critical defects**.

---

## 2. What AI Suggestions Were Retained and Why

| Retained Component | Engineering Rationale |
| :--- | :--- |
| **Monotonic Revisions (`revision_id`)** | Eliminates phone timestamps as ordering primitives, permanently solving Incidents 1 and 2. |
| **Semantic 3-Way Merge** | Enforces `Level = max(Server_Level, Client_Level)` and booster inventory union during offline sync conflicts. |
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

---

## 4. Critical Defects Discovered & Patched During Review

During the adversarial technical audit (STEP 3), five critical bugs in the generated code were caught, investigated, and patched:

1. **Post-Migration Coin Re-Inflation in `legacy.py`:**
   * *Defect:* Legacy sync previously executed `coins_balance = max(coins_balance, payload.coins)`. If a migrated v2.5 player synced from an old v2.4 client, their converted coins were re-credited, enabling currency duplication.
   * *Fix:* Added an audit check against `migration_records`. Migrated accounts can no longer have wallet balances altered by v2.4 syncs.
2. **Double-Spend Race Condition (Dialect Isolation) in `wallet_repo.py`:**
   * *Defect:* Concurrent spend requests against the same balance both succeeded in test environments because `SELECT ... FOR UPDATE` did not serialize reads on non-PostgreSQL drivers.
   * *Fix:* Implemented Optimistic Concurrency Control (OCC) checking `lock_version`. Version collisions trigger immediate rollback and balance re-evaluation, properly rejecting the second spend with a 400 error.
3. **Concurrent Save Revision Collisions in `save_sync_service.py`:**
   * *Defect:* Two devices submitting saves simultaneously with identical base revisions generated identical `next_revision` numbers, triggering an unhandled database `IntegrityError` (500 error).
   * *Fix:* Added collision handling to catch constraint violations, roll back, re-fetch the latest state, and execute a 3-way semantic merge.
4. **Progression Leaping Anomaly in `save_sync_service.py`:**
   * *Defect:* Semantic merge using `max(level)` allowed a hacked client to submit `level: 99999` and skip the game.
   * *Fix:* Added progression sanity validation rejecting single sync jumps exceeding 100 levels.
5. **Level Reward Farming Abuse in `wallet_service.py`:**
   * *Defect:* `/wallet/earn-coins` did not verify whether a level completion reward had already been granted.
   * *Fix:* Made level completion rewards strictly idempotent per player per level (`idempotency_key = f"level_reward_{player_id}_lvl_{level}"`).

---

## 5. Time Spent Breakdown

| Activity | Approximate Duration |
| :--- | :--- |
| Problem Decomposition, Fact Extraction & PDF Investigation | ~45 Minutes |
| Architecture, Data Modeling & Migration Policy Formulation | ~60 Minutes |
| Backend Prototype Implementation (FastAPI, Models, Services, APIs) | ~60 Minutes |
| Adversarial Technical Audit, Concurrency Testing & Defect Patching | ~60 Minutes |
| Final Written Assignment & AI Usage Documentation | ~45 Minutes |
| **Total Time Invested** | **~4.5 Hours** |

---

## 6. Conversation Logs

Full raw conversation transcripts containing all prompts, tool calls, and model outputs have been preserved directly from the session logs and will be submitted alongside this document.
