# Merge Kingdom 2.5 — REST API Specification

## 1. Overview & API Conventions

* **Base URL:** `/api/v1`
* **Content-Type:** `application/json`
* **Authentication:** Bearer JWT in the `Authorization` header (`Authorization: Bearer <token>`).
* **Device Identification:** All client requests must include `X-Device-Id` and `X-App-Version` headers.
* **Idempotency:** State-mutating endpoints (`POST`, `PUT`) accept an optional or required `Idempotency-Key` header (UUIDv4) to guarantee retry-safety.
* **Standard Error Response Format:**
```json
{
  "error_code": "INSUFFICIENT_FUNDS",
  "message": "Player has 120 gems, but 200 gems are required for this transaction.",
  "timestamp": "2026-11-18T14:22:00Z",
  "details": {
    "required": 200,
    "available": 120
  }
}
```

---

## 2. API Endpoints Catalog

| Domain | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| **Auth** | `POST` | `/auth/device-login` | Anonymous device-based login / registration |
| **Auth** | `POST` | `/auth/refresh` | Refresh expired access JWT |
| **Players** | `GET` | `/players/me` | Fetch player profile, devices, and entitlements |
| **Saves** | `GET` | `/saves/latest` | Retrieve current authoritative cloud save |
| **Saves** | `POST` | `/saves/sync` | Bidirectional save sync with revision OCC |
| **Saves** | `POST` | `/saves/resolve-conflict` | Explicit client conflict resolution submission |
| **Wallet** | `GET` | `/wallet/balance` | Retrieve server-authoritative coin and gem balances |
| **Wallet** | `POST` | `/wallet/spend` | Server-authoritative debit for store purchases |
| **Wallet** | `POST` | `/wallet/earn-coins` | Credit coins for verified level completion |
| **Purchases** | `POST` | `/purchases/verify` | Verify Apple / Google Play receipt & grant items |
| **Entitlements**| `GET` | `/entitlements` | List active permanent entitlements (No Ads) |
| **Migration** | `GET` | `/migration/status` | Check if player requires v2.4 -> v2.5 migration |
| **Migration** | `POST` | `/migration/migrate` | Execute or retry migration conversion |
| **Legacy** | `POST` | `/legacy/sync` | Adapter endpoint for legacy clients (v2.0 – v2.4) |
| **Admin** | `GET` | `/admin/players/{id}` | Inspect player state, saves, wallet, and history |
| **Admin** | `GET` | `/admin/metrics` | Overall sync conflicts, migration stats, DAU |

---

## 3. Detailed Request and Response Schemas

### 3.1 Authentication

#### `POST /auth/device-login`
Authenticates a device, creates a new player if unknown, or resumes the existing player session.
* **Headers:**
  * `X-Device-Id`: `d_pixel_99182`
  * `X-App-Version`: `2.5.0`
  * `X-Platform`: `Android`
* **Request Body:**
```json
{
  "device_id": "d_pixel_99182",
  "platform": "Android",
  "os_version": "Android 14",
  "app_version": "2.5.0"
}
```
* **Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "player_id": "p_8812",
  "is_new_player": false,
  "migration_required": false
}
```

---

### 3.2 Game Save & Synchronization

#### `GET /saves/latest`
Fetches the current authoritative cloud save.
* **Response (200 OK):**
```json
{
  "player_id": "p_8812",
  "revision_id": 48,
  "level": 160,
  "inventory": {
    "hammer": 3,
    "shuffle": 1
  },
  "game_state": {
    "grid_width": 7,
    "grid_height": 9,
    "unlocked_zones": [1, 2, 3]
  },
  "state_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "server_saved_at": "2026-11-18T10:15:30Z",
  "updated_by_device_id": "d_tablet_7712"
}
```

#### `POST /saves/sync`
Performs optimistic-concurrency save upload and synchronization.
* **Headers:**
  * `Authorization`: `Bearer <token>`
  * `Idempotency-Key`: `a5c2f309-84d2-43bb-81d3-3b47c94519f0`
* **Request Body:**
```json
{
  "base_revision_id": 48,
  "client_saved_at": "2026-11-18T10:20:00Z",
  "level": 161,
  "inventory": {
    "hammer": 2,
    "shuffle": 1
  },
  "game_state": {
    "grid_width": 7,
    "grid_height": 9,
    "unlocked_zones": [1, 2, 3]
  },
  "state_hash": "8f481c4e7f867455d31484e5659220febe1451f0ab9043e06180fcbb99e31d25"
}
```
* **Success Response (200 OK — Save Accepted):**
```json
{
  "status": "ACCEPTED",
  "revision_id": 49,
  "server_saved_at": "2026-11-18T10:20:01Z",
  "merged": false
}
```
* **Conflict Response (409 Conflict — Automatic Merge or Resolution Required):**
If another device updated the save in the interim:
```json
{
  "status": "CONFLICT",
  "message": "Base revision 48 is stale. Current server revision is 50.",
  "server_save": {
    "revision_id": 50,
    "level": 165,
    "inventory": {
      "hammer": 3,
      "shuffle": 2
    },
    "server_saved_at": "2026-11-18T10:19:45Z"
  },
  "auto_merged_save": {
    "level": 165,
    "inventory": {
      "hammer": 2,
      "shuffle": 2
    }
  }
}
```

---

### 3.3 Server-Authoritative Wallet & Transactions

#### `GET /wallet/balance`
Retrieves server-authoritative balances.
* **Response (200 OK):**
```json
{
  "player_id": "p_8812",
  "coins": 3400,
  "gems": 250,
  "lock_version": 12,
  "updated_at": "2026-11-18T12:00:00Z"
}
```

#### `POST /wallet/spend`
Debits currency server-side for an in-game store item.
* **Headers:**
  * `Idempotency-Key`: `e7b9e671-0668-45ee-9fa9-44d32a932598`
* **Request Body:**
```json
{
  "currency_type": "GEM",
  "amount": 50,
  "item_id": "booster_pack_hammer_3",
  "client_context": {
    "source_screen": "level_fail_popup"
  }
}
```
* **Response (200 OK):**
```json
{
  "transaction_id": "tx_99812401",
  "currency_type": "GEM",
  "amount_debited": 50,
  "balance_before": 250,
  "balance_after": 200,
  "items_granted": {
    "hammer": 3
  },
  "created_at": "2026-11-18T12:05:00Z"
}
```

#### `POST /wallet/earn-coins`
Credits coins for level completion. Validated against level boundaries.
* **Headers:**
  * `Idempotency-Key`: `f1c84110-388a-4cbe-b4f0-466d3a82207a`
* **Request Body:**
```json
{
  "level_completed": 161,
  "coins_earned": 50,
  "score": 12450
}
```
* **Response (200 OK):**
```json
{
  "transaction_id": "tx_99812402",
  "currency_type": "COIN",
  "amount_credited": 50,
  "balance_before": 3400,
  "balance_after": 3450,
  "created_at": "2026-11-18T12:10:00Z"
}
```

---

### 3.4 In-App Purchase Verification & Entitlements

#### `POST /purchases/verify`
Server validates store receipt with Google Play or Apple App Store.
* **Headers:**
  * `Idempotency-Key`: `store_tx_GPA.3341-8891-2311-00123`
* **Request Body:**
```json
{
  "store_platform": "GOOGLE_PLAY",
  "store_transaction_id": "GPA.3341-8891-2311-00123",
  "product_id": "gem_pack_tier_2",
  "receipt_data": "{\"orderId\":\"GPA.3341-8891-2311-00123\",\"packageName\":\"com.chaosengine.mergekingdom\",\"purchaseToken\":\"4k12j...\"}"
}
```
* **Response (200 OK):**
```json
{
  "verification_status": "VERIFIED",
  "store_transaction_id": "GPA.3341-8891-2311-00123",
  "product_id": "gem_pack_tier_2",
  "rewards_granted": {
    "gems": 500,
    "entitlements": []
  },
  "wallet_summary": {
    "coins": 3450,
    "gems": 700
  }
}
```

#### `GET /entitlements`
Returns all durable, server-verified entitlements.
* **Response (200 OK):**
```json
{
  "player_id": "p_8812",
  "entitlements": [
    {
      "entitlement_key": "no_ads",
      "is_active": true,
      "granted_by_source": "IAP_PURCHASE",
      "granted_at": "2026-03-15T09:30:00Z",
      "expires_at": null
    }
  ]
}
```

---

### 3.5 Legacy Client Synchronization Adapter

#### `POST /legacy/sync`
Maintains backward compatibility for versions 2.0 – 2.4 without breaking client contracts.
* **Request Body (v2.4 Format):**
```json
{
  "player_id": "p_8812",
  "saved_at": 1761700000,
  "level": 142,
  "coins": 5400,
  "inventory": { "hammer": 3, "shuffle": 1 },
  "no_ads": false
}
```
* **Processing Rules on Server:**
  1. If server holds `no_ads: true`, incoming `no_ads: false` is ignored. Server returns `no_ads: true`.
  2. If server has higher level, progression is preserved: `level = max(server.level, incoming.level)`.
  3. Returns standard v2.4 JSON structure so legacy client `OnCloudSave` accepts it seamlessly.
* **Response Body (v2.4 Formatted JSON):**
```json
{
  "player_id": "p_8812",
  "saved_at": 1761700500,
  "level": 142,
  "coins": 5400,
  "inventory": { "hammer": 3, "shuffle": 1 },
  "no_ads": true
}
```

---

### 3.6 Administrative Monitoring Endpoints

#### `GET /admin/players/{player_id}`
Returns a 360-degree diagnostic view for customer support agents.
* **Response (200 OK):**
```json
{
  "player_id": "p_8812",
  "devices": [
    {
      "device_id": "d_phone_1",
      "platform": "Android",
      "os_version": "Android 14",
      "app_version": "2.5.0",
      "last_seen_at": "2026-11-18T13:00:00Z"
    },
    {
      "device_id": "d_tablet_old",
      "platform": "Android",
      "os_version": "Android 7.0",
      "app_version": "2.1.0",
      "last_seen_at": "2026-11-17T08:00:00Z"
    }
  ],
  "wallet": {
    "coins": 3450,
    "gems": 700
  },
  "entitlements": {
    "no_ads": true
  },
  "save_state": {
    "revision_id": 49,
    "level": 161
  },
  "migration_record": {
    "status": "COMPLETED",
    "policy_applied": "PURCHASED_FIRST_PROTECTION",
    "original_coins": 5400,
    "lifetime_purchased_coins": 2000,
    "converted_coins": 3400,
    "converted_gems": 2000
  }
}
```
