from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q


from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver



class VaultEquity(models.Model):
    """
    Stores the company's available equity.
    For this stage:
    - Create the vault with an initial balance.
    - Add funds through add_equity().
    - Prevent the equity balance from becoming negative.

    ==================================== STRUCTURE ========================================
        user identifies the owner of the vault.
        vault_equity_value stores the current equity balance.
        add_equity() provides a controlled way to increase the balance.
        transaction.atomic() ensures the database operation is transactional.
        select_for_update() locks the vault row on databases that support row-level locking.
        The database constraint prevents a negative balance from being stored.
    ===================================== STRUCTURE ========================================
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vault_equities",
    )

    vault_equity_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(vault_equity_value__gte=0),
                name="vault_equity_nonnegative",
            ),
        ]

    def add_equity(self, amount):
        """
        Add capital to the vault.
        Later, this method can be called when an investor
        contributes funds to the company.
        """

        amount = Decimal(str(amount)).quantize(Decimal("0.01"))

        if amount <= Decimal("0.00"):
            raise ValidationError(
                "The amount added must be greater than zero."
            )

        if self.pk is None:
            raise ValidationError(
                "Save the vault before adding equity."
            )

        with transaction.atomic():
            vault = VaultEquity.objects.select_for_update().get(
                pk=self.pk
            )

            vault.vault_equity_value += amount
            vault.save(update_fields=[
                "vault_equity_value",
                "updated_at",
            ])

        self.refresh_from_db()

    def transfer_to_trading_pool(self, pool, amount):
        """Transfer company equity into a trading pool."""

        from decimal import Decimal
        from django.core.exceptions import ValidationError
        from django.db import transaction

        amount = Decimal(str(amount)).quantize(Decimal("0.01"))

        if amount <= Decimal("0.00"):
            raise ValidationError("Transfer amount must be greater than zero.")

        if self.pk is None or pool.pk is None:
            raise ValidationError("Save the vault and pool first.")

        with transaction.atomic():
            # Lock both records while the transfer is processed.
            vault = VaultEquity.objects.select_for_update().get(pk=self.pk)
            trading_pool = TradingPool.objects.select_for_update().get(
                pk=pool.pk
            )

            # Prevent transferring money between different users.
            if vault.user_id != trading_pool.user_id:
                raise ValidationError(
                    "The vault and trading pool must belong to the same user."
                )

            if vault.vault_equity_value < amount:
                raise ValidationError(
                    "Insufficient funds in the company vault."
                )

            # Update both balances.
            vault.vault_equity_value -= amount
            trading_pool.trading_pool_value += amount

            vault.save(update_fields=[
                "vault_equity_value",
                "updated_at",
            ])
            trading_pool.save(update_fields=[
                "trading_pool_value",
                "updated_at",
            ])

            # Record the successful transfer.
            PoolTransfer.objects.create(
                vault=vault,
                trading_pool=trading_pool,
                amount=amount,
            )

        # Refresh the original Python objects.
        self.refresh_from_db()
        pool.refresh_from_db()

    def __str__(self):
        return (
            f"{self.user}"
            f"{self.vault_equity_value}"
        )


class TradingPool(models.Model):
    """
    Holds company funds allocated for trading.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="trading_pools",
    )

    trading_pool_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def record_profit(
            self,
            amount,
            utility="XAU/USD",
            direction="BUY",
            description="",
    ):

        """Record a profit and add it to the trading pool."""

        amount = Decimal(str(amount)).quantize(Decimal("0.01"))

        if amount <= Decimal("0.00"):
            raise ValidationError(
                "Profit must be greater than zero."
            )

        with transaction.atomic():
            pool = TradingPool.objects.select_for_update().get(
                pk=self.pk
            )

            profit = ProfitTrade(
                user=pool.user,
                trading_pool=pool,
                utility_traded=utility,
                trade_direction=direction,
                profit_value=amount,
                description=description,
            )

            # Validate the record before saving it.
            profit.full_clean()

            pool.trading_pool_value += amount
            pool.save(update_fields=[
                "trading_pool_value",
                "updated_at",
            ])

            profit.save()

        self.refresh_from_db()

        return profit

    def record_loss(
            self,
            amount,
            utility="XAU/USD",
            direction="BUY",
            description="",
    ):

        """Record a loss and deduct it from the trading pool."""

        amount = Decimal(str(amount)).quantize(Decimal("0.01"))

        if amount <= Decimal("0.00"):
            raise ValidationError(
                "Loss must be greater than zero."
            )

        with transaction.atomic():
            pool = TradingPool.objects.select_for_update().get(
                pk=self.pk
            )

            if pool.trading_pool_value < amount:
                raise ValidationError(
                    "Insufficient funds in the trading pool."
                )

            loss = LossTrade(
                user=pool.user,
                trading_pool=pool,
                utility_traded=utility,
                trade_direction=direction,
                loss_value=amount,
                description=description,
            )

            # Validate before changing the balance.
            loss.full_clean()

            pool.trading_pool_value -= amount
            pool.save(update_fields=[
                "trading_pool_value",
                "updated_at",
            ])

            loss.save()

        self.refresh_from_db()

        return loss

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(trading_pool_value__gte=0),
                name="trading_pool_balance_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Trading Pool - {self.user}: {self.trading_pool_value}"



class PoolTransfer(models.Model):
    """Audit history of vault-to-trading-pool transfers."""

    vault = models.ForeignKey(
        VaultEquity,
        on_delete=models.PROTECT,
        related_name="pool_transfers",
    )

    trading_pool = models.ForeignKey(
        TradingPool,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    transfer_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transfer_date"]

    def __str__(self):
        return f"Transfer of {self.amount} to pool #{self.trading_pool_id}"



class ProfitTrade(models.Model):
    """Records profits earned from completed trades."""

    class TradeUtility(models.TextChoices):
        XAUUSD = "XAU/USD", "Gold (XAU/USD)"
        VOL = "VOL", "Volatility Index"
        UNKNOWN = "UNKNOWN", "Unknown"

    class TradeDirection(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="profit_trades",
    )

    trading_pool = models.ForeignKey(
        TradingPool,
        on_delete=models.PROTECT,
        related_name="profits",
    )

    profit_trade_date = models.DateTimeField(auto_now_add=True)

    utility_traded = models.CharField(
        max_length=10,
        choices=TradeUtility.choices,
        default=TradeUtility.XAUUSD,
    )

    trade_direction = models.CharField(
        max_length=4,
        choices=TradeDirection.choices,
        default=TradeDirection.BUY,
    )

    profit_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    description = models.CharField(
        max_length=255,
        blank=True,
    )

    def __str__(self):
        return (
            f"{self.utility_traded} | "
            f"Profit: {self.profit_value}"
        )



class LossTrade(models.Model):
    """Records losses incurred by completed trades."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loss_trades",
    )

    trading_pool = models.ForeignKey(
        TradingPool,
        on_delete=models.PROTECT,
        related_name="losses",
    )

    loss_trade_date = models.DateTimeField(auto_now_add=True)

    utility_traded = models.CharField(
        max_length=10,
        choices=ProfitTrade.TradeUtility.choices,
        default=ProfitTrade.TradeUtility.XAUUSD,
    )

    trade_direction = models.CharField(
        max_length=4,
        choices=ProfitTrade.TradeDirection.choices,
        default=ProfitTrade.TradeDirection.BUY,
    )

    loss_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    description = models.CharField(
        max_length=255,
        blank=True,
    )

    def __str__(self):
        return (
            f"{self.utility_traded} | "
            f"Loss: {self.loss_value}"
        )



class InvestorSharePool(models.Model):
    """Stores funds reserved for investors."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="investor_share_pool",
    )

    share_pool_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(share_pool_value__gte=0),
                name="investor_share_pool_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Investor Share Pool: {self.share_pool_value}"
