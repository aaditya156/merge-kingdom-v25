from typing import Optional, List
from sqlalchemy import select, desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.wallet import Wallet
from backend.app.models.ledger import CurrencyTransaction
from backend.app.models.base import utc_now


class InsufficientFundsException(Exception):
    def __init__(self, currency_type: str, required: int, available: int):
        self.currency_type = currency_type
        self.required = required
        self.available = available
        super().__init__(f"Insufficient {currency_type}: required {required}, available {available}")


class DuplicateTransactionException(Exception):
    def __init__(self, idempotency_key: str, existing_tx: CurrencyTransaction):
        self.idempotency_key = idempotency_key
        self.existing_tx = existing_tx
        super().__init__(f"Duplicate transaction with key {idempotency_key}")


class WalletRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_wallet(self, player_id: str, for_update: bool = False) -> Wallet:
        query = select(Wallet).where(Wallet.player_id == player_id)
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        wallet = result.scalar_one_or_none()
        if not wallet:
            wallet = Wallet(player_id=player_id, coins_balance=0, gems_balance=0, lock_version=0)
            self.session.add(wallet)
            await self.session.flush()
        return wallet

    async def get_transaction_by_idempotency(self, idempotency_key: str) -> Optional[CurrencyTransaction]:
        query = select(CurrencyTransaction).where(CurrencyTransaction.idempotency_key == idempotency_key)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_transaction_history(self, player_id: str, limit: int = 50) -> List[CurrencyTransaction]:
        query = (
            select(CurrencyTransaction)
            .where(CurrencyTransaction.player_id == player_id)
            .order_by(desc(CurrencyTransaction.created_at))
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def mutate_balance(
        self,
        player_id: str,
        currency_type: str,  # 'COIN' or 'GEM'
        amount: int,  # positive credit, negative debit
        transaction_type: str,
        reference_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> tuple[Wallet, CurrencyTransaction]:
        # 1. Idempotency check
        if idempotency_key:
            existing = await self.get_transaction_by_idempotency(idempotency_key)
            if existing:
                wallet = await self.get_wallet(player_id, for_update=False)
                return wallet, existing

        # 2. Lock wallet row exclusively & capture current version
        wallet = await self.get_wallet(player_id, for_update=True)
        initial_version = wallet.lock_version

        # 3. Check balance
        current_balance = wallet.coins_balance if currency_type == "COIN" else wallet.gems_balance
        new_balance = current_balance + amount

        if new_balance < 0:
            raise InsufficientFundsException(
                currency_type=currency_type,
                required=abs(amount),
                available=current_balance,
            )

        # 4. Atomic conditional update on lock_version (Optimistic Concurrency Control)
        update_values = {
            "lock_version": initial_version + 1,
            "updated_at": utc_now(),
        }
        if currency_type == "COIN":
            update_values["coins_balance"] = new_balance
        else:
            update_values["gems_balance"] = new_balance

        result = await self.session.execute(
            update(Wallet)
            .where(Wallet.id == wallet.id, Wallet.lock_version == initial_version)
            .values(**update_values)
        )

        if result.rowcount == 0:
            # OCC collision: Another concurrent transaction modified the wallet in the interim
            # Re-read fresh state and re-check balance
            await self.session.rollback()
            fresh_wallet = await self.get_wallet(player_id, for_update=True)
            fresh_balance = fresh_wallet.coins_balance if currency_type == "COIN" else fresh_wallet.gems_balance
            if fresh_balance + amount < 0:
                raise InsufficientFundsException(
                    currency_type=currency_type,
                    required=abs(amount),
                    available=fresh_balance,
                )
            return await self.mutate_balance(
                player_id=player_id,
                currency_type=currency_type,
                amount=amount,
                transaction_type=transaction_type,
                reference_id=reference_id,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )

        # 5. Create immutable ledger record
        tx = CurrencyTransaction(
            wallet_id=wallet.id,
            player_id=player_id,
            currency_type=currency_type,
            amount=amount,
            balance_before=current_balance,
            balance_after=new_balance,
            transaction_type=transaction_type,
            reference_id=reference_id,
            idempotency_key=idempotency_key,
            metadata_info=metadata or {},
        )
        self.session.add(tx)

        # Refresh local wallet object
        if currency_type == "COIN":
            wallet.coins_balance = new_balance
        else:
            wallet.gems_balance = new_balance
        wallet.lock_version = initial_version + 1

        await self.session.flush()
        return wallet, tx
