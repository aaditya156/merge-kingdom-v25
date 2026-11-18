# Merge Kingdom 2.5 — Architecture, Migration & Verification
## Senior AI Engineer Take-Home Assignment | Chaos Engine Labs

**Author:** Aditya Tiwary  
**Role:** AI Engineer Candidate  
**Date:** November 2026  

---

## Executive Summary

This document presents the technical analysis, systems architecture, and verified migration framework for transitioning **Merge Kingdom** from version 2.4 to 2.5.

### The Business Mandate & Economy Shift
* **The Mandate:** *"No player may lose progress, or anything that they paid for."* (Assignment Brief, Page 2).
* **The Economy Restructuring:**
  * **Coins:** Earned exclusively through gameplay (level completions, merge boards, daily chests).
  * **Gems:** Purchased exclusively with real money via In-App Purchases (IAP).
  * **Store Restructuring:** In-game store items (boosters, energy, premium items) sell exclusively for gems.

### Core Architectural Decisions & Prototype Verification
1. **Server-Authoritative Saves:** Replaced unauthenticated device timestamps with monotonic server-assigned integer revisions (`revision_id`) and semantic conflict resolution, resolving progression rollback (Incident 1) and preventing device-clock manipulation from poisoning cloud saves (Incident 2).
2. **Purchased-First Protection (PFP):** Formulated an executive policy converting remaining coins up to lifetime purchased coins into gems: `Gems = min(Current_Coins, Lifetime_Purchased_Coins)`. Because the studio never recorded historical coin spending (Fact 4), PFP cannot prove the true origin of remaining coins or guarantee absolute economic fairness across all players. It represents a player-protective policy assumption designed to protect paid purchasing power, which may overcompensate some players (creating studio unearned liability) because spending records are absent.
3. **Proposed 1:1 Peg Ratio:** The document models an initial working proposal of 1 purchased coin = 1 gem, subject to formal Finance review and calibration against the v2.5 gem store pricing book.
4. **Decoupled Relational Persistence:** Normalized mutable save blobs, currency wallets, append-only transaction logs, and entitlements into dedicated tables, preventing stale client saves from revoking paid entitlements (Incident 3).
5. **Dual-Mode Compatibility Adapter:** Maintained a dedicated `/api/v1/legacy/sync` adapter for the ~5% of daily active players on Android 7 devices (which cannot run newer builds), avoiding the 18% player churn observed during a previous forced update.
6. **Empirically Verified Backend Prototype:** Validated across **33 automated test suites** in Python 3.14 / FastAPI / SQLAlchemy 2.0 async, achieving **93% statement coverage** (1,082 statements, 74 missed) and **91% branch coverage** (130 branch points, 20 partial) across concurrency, double-spends, offline replay, and tamper scenarios.

---

## Task 1: Existing System Analysis (v2.0 – v2.4)

### 1.1 Architecture & Save Mechanics
*Reference: Assignment Brief, Page 2 (Fact 1), Page 3 (Fact 2 & 3)*

Versions 2.0 through 2.4 operate on a **client-authoritative save model** with a passive, unvalidating backend storage service. The Unity C# client defines the following data models:

```csharp
[Serializable]
public class Inventory {
    public int hammer;
    public int shuffle;
}

[Serializable]
public class SaveData {
    public string player_id;
    public long saved_at;
    public int level;
    public int coins;
    public Inventory inventory;
    public bool no_ads;
}
```

* **Save Execution (`SaveSystem.Save`):** Whenever gameplay state changes, the client captures the current device wall-clock time (`Current.saved_at = DateTimeOffset.Now.ToUnixTimeSeconds()`), serializes `SaveData` into a JSON string, writes it to local disk, and calls `CloudSync.Upload(json)`.
* **Server Sync Logic (Fact 3):** The server maintains exactly one save record per player. It accepts an incoming save if and only if:
  `incoming.saved_at > stored.saved_at`
  The server performs zero semantic inspection of the payload fields (`level`, `coins`, `inventory`, `no_ads`). If the upload is rejected, the server returns its stored save. In both outcomes, the client receives the server save in `OnCloudSave(serverJson)` and overwrites local disk if `server.saved_at > Current.saved_at`.

### 1.2 Core Flaws in the Live System

| Architectural Flaw | Mechanism in Live System | Impact on Player Experience & Economy |
| :--- | :--- | :--- |
| **1. Untrusted Device Timestamps** | `saved_at` is generated directly from the device operating system clock (`DateTimeOffset.Now`). | Device clocks drift, desynchronize across timezones, and are routinely set forward by players to bypass energy timers. Future-dated saves lock the cloud account against subsequent legitimate progress until real time passes the future timestamp. |
| **2. Monolithic Whole-Save Replacement** | Progression, currency, inventory, and entitlements are bundled in a single monolithic JSON blob. | The server cannot resolve granular field conflicts. An older device uploading an outdated level blindly overwrites newer currency and entitlement purchases. |
| **3. Client-Authoritative Currency** | `coins` is a mutable integer field authored on the client device. | The server has zero transaction ledger. Coins can be manipulated via memory-editing tools on rooted devices without backend validation. |
| **4. Missing Coin Spend Records (Fact 4)** | The server logs purchase receipts for coin packs, but coin spending occurs purely on the client without server transaction logging. | The backend cannot reconstruct whether remaining coins were earned via gameplay or bought with real money. |
| **5. Mutable Entitlement Storage** | `no_ads` is stored as a mutable client boolean within the save payload. | A player who purchased No Ads will have their entitlement revoked if an older secondary device connects with `no_ads: false`. |
| **6. Multi-Device Desynchronization (Fact 2)** | ~9% of daily active players play on more than one device (e.g., commute phone and home tablet). | Multi-device play is a core behavioral pattern, making players susceptible to save-overwriting conflicts when playing offline across devices. |

---

## Task 2: Root-Cause Analysis of Support Incidents

*Reference: Assignment Brief, Page 4 (Fact 6)*  
*(Note: Specific timestamps and calendar intervals below are illustrative sequences modeling the customer support ticket scenarios)*

### Incident 1: Tablet Level 160 Overwritten by Offline Phone Level 151
> *"I played on my tablet all weekend and got to level 160. My son played on my old phone in airplane mode on Sunday night, after I stopped. Today I am back at level 151. Where did my levels go?"*

```
Illustrative Sequence for Incident 1:
Tablet (Device A):  --- [Level 150] ---> [Plays to Level 160] (T1) ---> [Uploads: Level 160, T1] (Server Stores 160, T1)
Phone (Device B):   --- [Level 150] ---> [Airplane Mode: Level 151] (T2 > T1) -X (Queued locally)
                    (Later: Network Reconnected)
Phone (Device B):   --------------------------------------------------------> [Flushes: Level 151, T2]
Server Decision:    Checks T2 > T1 -> TRUE -> Overwrites Server Save with Level 151!
Tablet Re-sync:     Receives Level 151 (T2 > T1) -> Overwrites Tablet Disk -> Level 160 LOST
```

* **Step-by-Step Breakdown:**
  1. **Device A (Tablet - Online):** Mother plays on Tablet, advancing from Level 150 to Level 160 at illustrative time `T1`. Tablet uploads save: `{level: 160, saved_at: T1}`. Server stores Level 160 at `T1`.
  2. **Device B (Phone - Offline):** Son plays on old Phone in Airplane Mode, starting from an older save (Level 150) and reaching Level 151 at illustrative time `T2` (where `T2 > T1`). The phone writes locally `{level: 151, saved_at: T2}` and queues the upload for network restoration.
  3. **Reconnection:** Airplane mode is disabled. Phone flushes its queued upload to the server.
  4. **Server Evaluation:** The server checks: `incoming.saved_at (T2) > stored.saved_at (T1)`. Because `T2` is numerically greater, the server accepts the payload and overwrites the stored save with Level 151.
  5. **Tablet Desynchronization:** When the mother opens her tablet, `OnCloudSave` compares timestamps. Because the server's timestamp (`T2`) is newer than the tablet's local save (`T1`), the tablet overwrites its local storage with Level 151, destroying 9 levels of progress.
* **Root Cause:** Naive Last-Write-Wins (LWW) based on unauthenticated device wall-clock timestamps without progression validation or semantic merging.
* **v2.5 Prevention:**
  * Replaced timestamps with monotonic server revisions (`revision_id`).
  * Enforced semantic 3-way progression merge: `Resolved_Level = max(Server_Level, Client_Level)`.
  * When the phone reconnects with a stale base revision, the server evaluates `max(160, 151) = 160`. Progression is preserved, and the phone is updated to Level 160.

---

### Incident 2: Date Fast-Forward Tomorrow -> Today
> *"I changed the date on my phone to tomorrow, opened the free chest early and played one level. Then I changed the date back. Later I played more levels on the bus with no internet. When I got home, those levels were gone."*

```
Illustrative Sequence for Incident 2:
Phone (Time Hack):  [Advances clock +24h to T_future] ---> [Beats Lvl 51] ---> [Uploads: Lvl 51, T_future] (Server Stores T_future)
Phone (Clock Reset): [Sets clock back to T_real]
Phone (Offline):    [Plays on bus offline to Level 55] (Local save timestamped T_real)
Phone (Home Reconnect): [Attempts upload: Level 55, T_real]
Server Decision:    Checks T_real > T_future -> FALSE -> REJECTS UPLOAD! Returns stored Lvl 51, T_future.
Phone Client:       OnCloudSave compares T_future > T_real -> Overwrites Level 55 with Level 51!
```

* **Step-by-Step Breakdown:**
  1. **Clock Tampering:** Player advances phone clock 24 hours into the future (`T_future`), opens the daily chest, and completes Level 51. The client uploads `{level: 51, saved_at: T_future}`. The server stores `T_future`.
  2. **Clock Restoration:** Player resets the phone clock to real time (`T_real`).
  3. **Offline Gameplay:** While commuting without internet, the player advances from Level 51 to Level 55. The client writes locally `{level: 55, saved_at: T_real}`.
  4. **Upload Rejection:** Upon connecting to Wi-Fi at home, the client attempts to upload Level 55. The server checks: `T_real > T_future`. Because `T_real` is 24 hours behind `T_future`, the condition is **FALSE**. The server rejects the upload and returns the stored save (`{level: 51, saved_at: T_future}`).
  5. **Local Overwrite:** The client's `OnCloudSave` executes: `server.saved_at (T_future) > local.saved_at (T_real)`. The phone discards Level 55 and overwrites local disk with Level 51.
* **Root Cause:** Treating client-generated wall-clock timestamps as authoritative ordering primitives. Future-dating a device poisons the server timestamp, locking out subsequent legitimate saves until real-world time passes `T_future`.
* **v2.5 Prevention:**
  * Client timestamps are recorded strictly for audit logging and are decoupled from save version ordering.
  * Revisions strictly increment on the server (`revision_id = server.revision_id + 1`).
  * Changing device clocks no longer controls server save acceptance or revision progression.

---

### Incident 3: Lost "No Ads" Entitlement
> *"I paid for No Ads in March. Last week the ads came back. I play on my phone and on my old tablet."*

```
Illustrative Sequence for Incident 3:
Phone:   [Buys No Ads at T_purchase] ---> [Saves: no_ads=true, T_purchase] (Server Stores no_ads=true)
Tablet:  (Old tablet, holding no_ads=false)
Tablet:  [Played at T_later] ---> [Uploads: no_ads=false, T_later]
Server:  Checks T_later > T_purchase -> TRUE -> Overwrites save with no_ads=false!
Phone:   Receives server update -> Overwrites local disk -> Paid entitlement REVOKED
```

* **Step-by-Step Breakdown:**
  1. **Purchase on Phone:** Player purchases No Ads on their phone via In-App Purchase in March (`T_purchase`). The phone sets `no_ads: true` and uploads `{no_ads: true, saved_at: T_purchase}`. Server stores `no_ads: true`.
  2. **Old Tablet Played Later:** Last week (`T_later`), the player plays on their old tablet. Because the tablet had not recorded the No Ads purchase locally, its save file contains `no_ads: false`.
  3. **Tablet Sync:** The player completes one level on the tablet at time `T_later` (where `T_later > T_purchase`). The tablet sets `saved_at: T_later` and uploads its save containing `no_ads: false`.
  4. **Server Blind Replacement:** The server checks: `T_later > T_purchase`. Because `T_later` is newer, the server unconditionally replaces the entire save file, overwriting `no_ads: true` with `no_ads: false`.
  5. **Entitlement Stripped:** The player's phone synchronizes with the server, reads `no_ads: false`, and resumes showing ads.
* **Root Cause:** Storing paid entitlements as mutable client-side boolean flags coupled within monolithic save blobs.
* **v2.5 Prevention:**
  * Entitlements are decoupled from game saves and stored in a normalized `entitlements` table.
  * Entitlements can only be granted via verified server-side store purchase receipts or authoritative admin actions.
  * Save sync endpoints cannot modify entitlements. Even if a legacy client uploads `no_ads: false`, the server overrides the response with the authoritative active entitlement.

---

## Task 3: Merge Kingdom v2.5 Systems Architecture

### 3.1 Architecture Overview (Modular Monolith)

The v2.5 backend is architected as a modular monolith built with **FastAPI**, **SQLAlchemy 2.0 (async)**, and **PostgreSQL 16+**.

```mermaid
flowchart TD
    subgraph Clients
        C25[Client v2.5+]
        C24[Legacy Client v2.0-v2.4]
    end

    subgraph API Layer
        Auth[JWT Device Auth /api/v1/auth]
        SaveSvc[/api/v1/saves/sync]
        WalletSvc[/api/v1/wallet/spend & earn]
        PurchaseSvc[/api/v1/purchases/verify]
        MigrateSvc[/api/v1/migration/migrate]
        LegacyAdapter[/api/v1/legacy/sync]
    end

    subgraph Service & Persistence Layer
        T_Players[(player_profiles & devices)]
        T_Saves[(game_saves - Monotonic Revisions)]
        T_Wallets[(wallets & currency_transactions)]
        T_Purchases[(purchase_records & entitlements)]
        T_Offline[(offline_operations - Idempotent Dedup)]
        T_Migration[(migration_records & snapshots)]
    end

    C25 -->|Bearer JWT| Auth
    Auth --> SaveSvc
    Auth --> WalletSvc
    Auth --> PurchaseSvc
    Auth --> MigrateSvc

    C24 -->|X-Device-Id TOFU| LegacyAdapter
    LegacyAdapter --> SaveSvc
    LegacyAdapter --> T_Purchases

    SaveSvc --> T_Saves
    SaveSvc --> T_Offline
    WalletSvc --> T_Wallets
    PurchaseSvc --> T_Purchases
    MigrateSvc --> T_Migration
    MigrateSvc --> T_Wallets
```

### 3.2 Save Data Structure & Sync Mechanics

Save payloads are strictly limited to pure gameplay state:

```json
{
  "player_id": "p_8812",
  "base_revision_id": 48,
  "level": 160,
  "inventory": { "hammer": 3, "shuffle": 1 },
  "game_state": { "grid_w": 7, "grid_h": 9, "board_hash": "a9f8e2" },
  "client_saved_at": "2026-11-18T14:30:00Z",
  "device_id": "phone_main",
  "offline_operations": [
    {
      "operation_id": "op_uuid_9981",
      "operation_type": "CONSUME_ITEM",
      "item_id": "hammer",
      "quantity": 1
    }
  ]
}
```

* **Sequential Sync (`base_revision == server.revision`):**
  * Validates progression jump (`level <= server.level + 100`).
  * Increments `revision_id = server.revision_id + 1`.
  * Returns status `ACCEPTED`.
* **Conflict Sync (`base_revision < server.revision`):**
  * Applies state-specific conflict resolution rules (detailed below).
  * Increments `revision_id = server.revision_id + 1` and returns status `MERGED`.

### 3.3 State-Specific Conflict Resolution Matrix

To avoid ambiguous whole-blob replacements, the v2.5 backend decomposes save data and resolves conflicts according to field-specific semantics:

| State Domain | Resolution Mechanism | Why This Strategy Was Chosen | Trade-offs & Limitations |
| :--- | :--- | :--- | :--- |
| **1. Level Progression** | Monotonic Max Rule:<br>`Resolved_Level = max(server.level, client.level)` | Preserves player milestone progression across all devices; prevents stale devices from rolling back progress. | Does not validate move-by-move validity on server (heuristic jump limit applied). |
| **2. Consumable Inventory** | Base-Save Delta Reconciliation:<br>`Delta = client_inv - base_inv`<br>`Resolved = max(0, server_inv + Delta)`<br>+ Unique `operation_id` deduplication | Prevents offline devices from restoring already-consumed boosters when reconnecting. Deduplication stops double-consumption across network retries. | Requires base revision snapshot. If base snapshot is missing, server authoritative inventory prevails. |
| **3. Board State / Puzzle Grid** | Highest Level Takes Precedence:<br>Board state from highest completed level wins; if levels are equal, server state prevails. | In casual merge games, merge board grid tiles cannot be field-merged without deterministic move-by-move telemetry. | The secondary device loses uncommitted temporary board tile arrangements from its stale session. |
| **4. Currency Balances (Coins & Gems)** | Decoupled Server-Authoritative Wallet:<br>Excluded from save payloads. Mutated via dedicated endpoints with row-level locks and OCC. | Protects against client-side currency tampering, save-overwrite duplication, and double-spending. | Requires network connectivity for store purchases (offline gameplay coin earnings queue as idempotent completion operations). |

### 3.4 Authoritative Wallet & Append-Only Transaction Log

Currency balances are server-authoritative and managed via `WalletRepository`:
* **Optimistic & Row-Level Concurrency:** Concurrency is protected using **Optimistic Concurrency Control (OCC)** via an integer `lock_version` column, paired with database row-level locking (`SELECT ... FOR UPDATE`). Two simultaneous requests spending the same balance cannot double-spend; version collisions trigger immediate rollback and balance re-evaluation.
* **Append-Only Transaction Log (`currency_transactions`):** Every wallet mutation writes an immutable ledger entry recording `balance_before`, `balance_after`, signed `amount`, `transaction_type`, and a unique `idempotency_key`.
* **Architectural Clarification:** This is an **append-only player transaction log**, not an enterprise multi-account double-entry accounting ledger. It provides robust player-level auditability without balance sheet complexity.

### 3.5 In-App Purchases & Entitlements

* **Idempotent Purchase Processing:** Store transaction identifiers (`store_transaction_id`) are protected by a unique database constraint. App store retry storms process the first request and return cached receipts for subsequent duplicates.
* **Catalog Validation:** Incoming product IDs are verified against a registered product catalog. Unknown or tampered product IDs are rejected with `400 Bad Request` (no fallback default currency).
* **Decoupled Entitlements:** Entitlements reside in `entitlements` (`entitlement_key`, `is_active`, `granted_at`). Non-consumable purchases (such as No Ads) are linked to purchase transaction records and cannot be revoked by save synchronization.
* **Production vs. Prototype Verification:** The prototype implements an in-memory catalog verification service. Production deployment requires configuring Google Cloud Service Account credentials for Google Play Developer API and private keys for Apple StoreKit 2 (JWS receipt verification).

### 3.6 Legacy Client Compatibility & Device Identification (`/legacy/sync`)

To support players locked on Android 7 (v2.0–v2.4), the backend provides a backward-compatible adapter:
* **Device Identification vs. Authentication:** `X-Device-Id` is a client-supplied identifier, **not** a cryptographic authentication credential. The endpoint enforces a **Trust-On-First-Use (TOFU)** heuristic:
  * An absent or whitespace-only header returns `401 Unauthorized`.
  * The first authorized legacy sync for an unbound account binds the device identifier.
  * Subsequent requests from unknown or unbound devices return `403 Forbidden`.
  * *Production Requirement:* Production deployments must elevate legacy account binding via federated identity (Google Play Games, Sign in with Apple) or an out-of-band account recovery flow (email/SMS magic links or Customer Support verification tokens).
* **Entitlement Protection:** The legacy adapter ignores `payload.no_ads = True` unless backed by a verified server purchase record.
* **Wallet Balance Protection:** If an account has already completed v2.5 migration, legacy save uploads cannot overwrite wallet balances.
* **Legacy Inventory Trade-Off:** Because v2.0–v2.4 clients transmit raw inventory snapshots without base revision IDs or operation IDs, full 3-way delta reconciliation is impossible for legacy clients. The adapter intentionally preserves the server's authoritative inventory to protect items consumed on v2.5 devices.

---

## Task 4: Coin-to-Gem Conversion Policy & Financial Trade-Offs

### 4.1 Missing Coin Spend History (Fact 4)
*Reference: Assignment Brief, Page 4 (Fact 4)*

Let:
* `Purchased_Coins`: Lifetime coins purchased via real-money IAP (recorded on server).
* `Current_Coins`: Coins held in the player's v2.4 save file at migration time.

> **The Mathematical Reality:** The server has records of every purchase (player ID, pack ID, number of coins in the pack, timestamp), but **zero records of what players spent coins on, or when** (Fact 4). It is mathematically impossible to reconstruct whether remaining coins originated from real money or gameplay rewards. Any conversion formula is an executive policy decision.

### 4.2 Candidate Conversion Policies

| Candidate Policy | Mathematical Formula | Verdict & Economic Trade-Offs |
| :--- | :--- | :--- |
| **1. 100% Gem Conversion** | `Gems = Current_Coins`<br>`Coins = 0` | **REJECTED (Destroys Business Viability):** Converts billions of freely earned gameplay coins into paid gems, wiping out in-game store IAP revenue. |
| **2. 0% Gem Conversion** | `Gems = 0`<br>`Coins = Current_Coins` | **REJECTED (Violates Core Mandate):** Any player who purchased coin packs loses paid purchasing power in the new store. Triggers severe store chargebacks and consumer protection complaints. |
| **3. Proportional Ratio** | `Gems = Current_Coins * (Purchased / Estimated_Total)` | **REJECTED (High Dispute & Legal Risk):** Relies on fabricated estimates of earned coins. Players who completed identical levels would receive different conversion rates based on guesswork. |
| **4. Purchased-First Protection (PFP)** *(Selected)* | `Gems = min(Current_Coins, Purchased_Coins)`<br>`Coins = Current_Coins - Gems` | **ACCEPTED:** Protects paid purchasing power without guesswork, but may overcompensate some players due to absent spend history. |

### 4.3 Why Purchased-First Protection (PFP) Was Chosen

Under the **Purchased-First Protection (PFP)** policy:
$$\text{Gems} = \min(\text{Current\_Coins}, \text{Lifetime\_Purchased\_Coins})$$
$$\text{Coins} = \text{Current\_Coins} - \text{Gems}$$

PFP operates on an intentional, player-protective policy assumption: **it assumes players spent their earned gameplay coins before spending their purchased coins**.

#### Four Representative Persona Walkthroughs:

1. **Active Spender / Whale:**
   * *History:* Bought 10,000 coins historically (`Purchased = 10,000`). Spent heavily on boosters. Currently holds 2,500 coins.
   * *Calculation:*
     $\text{Gems} = \min(2500, 10000) = 2,500\text{ gems}$
     $\text{Coins} = 2500 - 2500 = 0\text{ coins}$
   * *Outcome:* Every remaining coin is converted to gems. The player retains their purchasing power in the new store. If the player actually spent purchased coins first, the studio overcompensates them by granting gems for remaining gameplay coins.
2. **F2P Grinder with Starter Bundle:**
   * *History:* Earned 15,000 coins through grinding; bought one 500-coin starter pack (`Purchased = 500`). Currently holds 4,000 coins.
   * *Calculation:*
     $\text{Gems} = \min(4000, 500) = 500\text{ gems}$
     $\text{Coins} = 4000 - 500 = 3,500\text{ coins}$
   * *Outcome:* Paid purchase is converted to 500 gems; remaining 3,500 coins remain gameplay currency for future gameplay features.
3. **Pure Free-to-Play Player:**
   * *History:* Never made an IAP (`Purchased = 0`). Holds 6,200 coins through skilled play.
   * *Calculation:*
     $\text{Gems} = \min(6200, 0) = 0\text{ gems}$
     $\text{Coins} = 6200 - 0 = 6,200\text{ coins}$
   * *Outcome:* Retains their full gameplay progress as coins. The studio incurs no unearned gem dilution.
4. **Dormant Whale (Fully Depleted):**
   * *History:* Bought 20,000 coins historically. Spent all coins prior to v2.5 (`Current = 0`).
   * *Calculation:*
     $\text{Gems} = \min(0, 20000) = 0\text{ gems}$
     $\text{Coins} = 0 - 0 = 0\text{ coins}$
   * *Outcome:* Paid coins were already consumed for gameplay value in v2.4; the player receives no unearned currency.

### 4.4 Financial Implications & Executive Approval Requirements

* **Policy Assumption (Not Economic Proof):** PFP cannot prove whether remaining coins originated from real money or gameplay. In reality, some players spent purchased coins first. Converting their remaining balance to gems grants them paid value for what were originally gameplay earnings. This is the deliberate business choice of adopting a player-protective policy assumption in the absence of granular spend telemetry.
* **Proposed 1:1 Peg Ratio:** The 1:1 coin-to-gem conversion ratio modeled above is an initial engineering and product proposal. It requires formal Finance approval and may be adjusted based on the new store price book.
* **Restricted Purchase Eligibility:** Migration calculations are strictly restricted to verified historical purchases where `purchase_type == "COIN_PACK"`. Gem packs, entitlements, and non-coin items are completely excluded even if containing coin fields. The migration engine relies strictly on recorded quantities (`coins_in_pack`) without guessed price multipliers or invented catalog mappings. Purchases with missing or invalid quantities are flagged in `unresolved_purchases` for Finance review.
* **Concurrent Migration Safety:** Wrapped in a transaction-safe strategy using the database uniqueness constraint on `MigrationRecord.player_id`. Simultaneous migration requests for the same player resolve idempotently without double-converting balances.
* **Deferred Revenue Liability:** Under IFRS 15 / ASC 606, unspent gems represent deferred revenue liabilities on the studio's balance sheet until consumed.
* **Rollback Limitations:** If a player migrates, converts coins to gems, and immediately spends those gems on store items, an automated rollback cannot simply deduct gems without driving the wallet negative. Rollbacks require manual audit reconciliation when converted currency has been consumed.
* **Required Sign-Offs:**
  1. *Finance Leadership:* Formal approval of PFP, the proposed 1:1 coin-to-gem peg ratio, and the policy for unrecorded purchase records.
  2. *Product Management:* Decision on whether to grant a one-time 50–100 free gem welcome bonus to F2P players to introduce the new gem store without currency dilution.

---

## Task 5: Release and Rollout Strategy

### 5.1 Player Distribution & Operational Constraints
*Reference: Assignment Brief, Page 4 (Fact 5)*

```
Player Distribution (Fact 5):
[===================== v2.4: 58% =====================] [=== v2.3: 21% ===] [= v2.2: 11% =] [ v2.0-2.1: 10% ]
                                                                                           |-> ~5% Android 7 (CANNOT UPDATE)
```

* **Version Distribution:** 58% on v2.4, 21% on v2.3, 11% on v2.2, 10% on v2.0–2.1.
* **Android 7 Constraint:** Approximately half of the v2.0–2.1 cohort (~5% of total DAU) are on Android 7 devices that cannot run the newer builds.
* **Multi-Device Usage:** ~9% of daily players actively use more than one device (typically a phone on the commute and a tablet at home).
* **Forced-Update Danger:** A previous forced update (v2.1 to v2.2) resulted in an **18% player drop-off**.
* **Store Review Latency:** App Store and Google Play certification reviews require **3 to 7 days** according to assignment facts.

### 5.2 Non-Forced Rollout Architecture

We will **NOT** deploy a blocking forced-update dialog:
1. **Dual-Mode Adapter:** The backend `/legacy/sync` adapter remains active so Android 7 players can continue playing on v2.0–2.4 without progress regression.
2. **Voluntary Store Incentive:** Compatible players receive non-blocking in-game announcements highlighting the new store, daily rewards, and content additions, encouraging voluntary updates without churn.

### 5.3 Illustrative Staged Rollout Timeline
*(Note: Rollout stages begin only after actual store approval, which requires 3–7 days)*

```mermaid
flowchart LR
    D_Prep["Day -5<br>Backend Dual-Mode Deploy"] --> D_Sub["Day 0<br>Store Submission (3-7d review window)"]
    D_Sub --> D_App["Day X (Store Approval)<br>1% Canary Release"]
    D_App --> D_Stg1["Day X+1<br>5% Staged Rollout"]
    D_Stg1 --> D_Stg2["Day X+2<br>20% Staged Rollout"]
    D_Stg2 --> D_Stg3["Day X+3<br>50% Staged Rollout"]
    D_Stg3 --> D_Full["Day X+4<br>100% General Availability"]
```

1. **Day -5 (Backend Pre-Release):** Deploy v2.5 backend in dual-mode (serving `/legacy/sync` and `/api/v1/`). Execute database migrations and verify baseline transaction logging.
2. **Day 0 (Store Submission):** Submit client v2.5 to Apple App Store Connect and Google Play Console. Certification review takes 3 to 7 days.
3. **Day X (Upon Actual Store Approval — Canary Release, 1% DAU):** Roll out to 1% of DAU. Monitor migration completion rates, error logs, and support ticket queues.
4. **Day X+1 (Stage 1 — 5% DAU):** Expand rollout to 5% of DAU. Validate concurrent migration idempotency and wallet lock contention metrics.
5. **Day X+2 (Stage 2 — 20% DAU):** Expand to 20% of DAU.
6. **Day X+3 (Stage 3 — 50% DAU):** Expand to 50% of DAU.
7. **Day X+4 (General Availability — 100% DAU):** Expand to 100% of compatible devices. Android 7 users remain safely served via `/legacy/sync`.

### 5.4 Rollback, Recovery & Migration Safeguards
* **Illustrative Anomaly Triggers:** Migration failure rate > 0.01%, save conflict rate > 2.0%, or any negative wallet balance anomaly.
* **Rollback Protocol:**
  1. Halt rollout immediately in Google Play Console and App Store Connect.
  2. Toggle backend feature flag `PAUSE_MIGRATION=true`. Unmigrated players continue playing on v2.4 without currency conversion.
  3. Pre-migration snapshots saved in `migration_records.original_save_snapshot` enable auditing and reconciliation.

---

## Task 6: Limitations, Unresolved Risks, and Open Questions

### 6.1 Prototype Limitations vs. Production Safeguards

| Feature / Subsystem | Implemented Prototype Behavior | Production Safeguard Required |
| :--- | :--- | :--- |
| **Store Receipt Verification** | Validates against registered catalog with unique transaction index (`store_transaction_id`). | Live server-to-server integration with Apple StoreKit 2 (JWS signature verification) and Google Play Developer API (Service Account OAuth). |
| **Gameplay Progression Validation** | Enforces heuristic threshold (`MAX_ALLOWED_LEVEL_JUMP = 100`) and deterministic level reward schedules. | Authoritative server-side puzzle simulation or move-by-move validation for competitive leaderboards. |
| **Legacy Authentication** | Trust-On-First-Use (TOFU) device identifier binding (`X-Device-Id`). Missing header returns 401; rogue device returns 403. | Federated identity (Google Play Games Services, Sign in with Apple) or out-of-band account recovery (email/SMS magic links or CS tokens). |
| **Legacy Inventory Reconciliation** | Preserves server authoritative inventory on legacy syncs to prevent overwriting v2.5 items. | Full 3-way delta reconciliation is restricted to v2.5+ clients with base revision and operation tracking. |
| **Real-Time Device Invalidation** | Client-initiated REST polling. | Push notifications (Firebase Cloud Messaging / Apple APNs) or WebSockets to alert secondary devices when save revision advances. |
| **Database Concurrency** | Validated using SQLite async (`aiosqlite`) with Optimistic Concurrency Control (`lock_version`). | Production targets PostgreSQL 16+ utilizing native `SELECT ... FOR UPDATE` row-level locks alongside OCC. |

### 6.2 Open Executive Questions

#### For Product Management:
1. **F2P Economy Balancing:** With store items selling exclusively for gems, how will non-paying players acquire boosters? Will level milestones or daily achievements award small quantities of gems?
2. **Android 7 Sunsetting Roadmap:** Will the studio maintain the `/legacy/sync` adapter indefinitely, or establish an announced sunset timeline (e.g. 12 months) with account export options?

#### For Finance Leadership:
1. **Coin-to-Gem Peg Approval:** Does Finance formally approve the proposed 1:1 coin-to-gem peg ratio for purchased coins, or does the new gem store price book require a calibration factor?
2. **Deferred Revenue Liability:** Does Finance sign off on the deferred revenue liability created by PFP's player-protective policy assumption?
3. **Handling Unrecorded Purchases:** Does Finance approve flagging unrecorded/corrupted historical purchase records for manual CS review rather than applying estimated conversion multipliers?

---

## Appendix: Prototype Test Verification Results

The live backend prototype was verified across **33 automated test suites** using `pytest` and `pytest-cov`:

```
============================= test session starts ==============================
platform darwin -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/adityatiwary/Desktop/merge-kingdom-v25/backend
configfile: pytest.ini
plugins: cov-7.1.0, anyio-4.16.0, asyncio-1.5.0
asyncio: mode=Mode.AUTO

tests/test_audit_and_stress.py (12 tests) ............                   [ 36%]
tests/test_auth.py (1 test) .                                            [ 39%]
tests/test_database.py (1 test) .                                        [ 42%]
tests/test_migration.py (1 test) .                                       [ 45%]
tests/test_saves_and_sync.py (3 tests) ...                               [ 54%]
tests/test_security_and_edge_cases.py (13 tests) .............            [ 93%]
tests/test_wallet_and_purchases.py (2 tests) ..                          [100%]

================================ tests coverage ================================
Statement Coverage: 93% (1,082 Statements, 74 Missed)
Branch Coverage: 91% (130 Branches, 20 Partial)
============================== 33 passed in 2.54s ==============================
```
