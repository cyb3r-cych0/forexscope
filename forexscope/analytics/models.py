from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from decimal import Decimal, ROUND_DOWN
from django.db.models import Sum



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

    def distribute_profit(self, profit, vault):
        """
        Distribute a recorded profit:
        50% to the vault, 50% to the investor share pool.
        """

        with transaction.atomic():
            # Reload and lock the relevant records.
            pool = TradingPool.objects.select_for_update().get(pk=self.pk)
            profit = ProfitTrade.objects.select_for_update().get(pk=profit.pk)
            vault = VaultEquity.objects.select_for_update().get(pk=vault.pk)

            # Validate ownership and relationships.
            if profit.trading_pool_id != pool.pk:
                raise ValidationError(
                    "This profit does not belong to this trading pool."
                )

            if profit.user_id != pool.user_id:
                raise ValidationError(
                    "The profit and trading pool must have the same owner."
                )

            if vault.user_id != pool.user_id:
                raise ValidationError(
                    "The vault and trading pool must have the same owner."
                )

            if SharePoolDistribution.objects.filter(profit=profit).exists():
                raise ValidationError(
                    "This profit has already been distributed."
                )

            amount = profit.profit_value

            if amount <= Decimal("0.00"):
                raise ValidationError("Profit must be greater than zero.")

            # Ensure the pool can cover the distribution.
            if pool.trading_pool_value < amount:
                raise ValidationError(
                    "Insufficient funds in the trading pool."
                )

            # Calculate the 50/50 split.
            reinvestment = (amount * Decimal("0.50")).quantize(
                Decimal("0.01")
            )
            investor_amount = amount - reinvestment

            # Get or create this user's investor share pool.
            share_pool, _ = InvestorSharePool.objects.get_or_create(
                user=pool.user
            )

            share_pool = InvestorSharePool.objects.select_for_update().get(
                pk=share_pool.pk
            )

            # Update all three balances.
            pool.trading_pool_value -= amount
            vault.vault_equity_value += reinvestment
            share_pool.share_pool_value += investor_amount

            pool.save(update_fields=[
                "trading_pool_value",
                "updated_at",
            ])

            vault.save(update_fields=[
                "vault_equity_value",
                "updated_at",
            ])

            share_pool.save(update_fields=[
                "share_pool_value",
                "updated_at",
            ])

            # Record the distribution.
            distribution = SharePoolDistribution(
                profit=profit,
                vault=vault,
                share_pool=share_pool,
                total_profit=amount,
                reinvestment_amount=reinvestment,
                investor_amount=investor_amount,
            )

            distribution.full_clean()
            distribution.save()

        self.refresh_from_db()
        vault.refresh_from_db()
        share_pool.refresh_from_db()

        return distribution

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

    
    def distribute_to_investors(self):
        """
        Allocate the entire available investor share pool
        proportionally to investor contributions.

        This records allocations; it does not transfer money
        to external bank accounts.
        """

        cent = Decimal("0.01")

        with transaction.atomic():
            share_pool = InvestorSharePool.objects.select_for_update().get(
                pk=self.pk
            )

            if share_pool.share_pool_value <= Decimal("0.00"):
                raise ValidationError(
                    "There are no funds available for distribution."
                )

            # Find each investor's contributions to this user's vaults.
            contributions = (
                InvestorContribution.objects
                .filter(vault__user=share_pool.user)
                .values("investor_id", "investor__investor_name")
                .annotate(total=Sum("amount"))
                .filter(total__gt=0)
                .order_by("investor_id")
            )

            investors = list(contributions)

            if not investors:
                raise ValidationError(
                    "No eligible investor contributions were found."
                )

            total_contributions = sum(
                (item["total"] for item in investors),
                Decimal("0.00"),
            )

            available = share_pool.share_pool_value
            allocations = []
            allocated_total = Decimal("0.00")

            # Calculate each share, rounding down to cents.
            for item in investors[:-1]:
                investor_amount = (
                    available * item["total"] / total_contributions
                ).quantize(cent, rounding=ROUND_DOWN)

                if investor_amount > 0:
                    allocations.append(
                        (item, investor_amount)
                    )
                    allocated_total += investor_amount

            # Give the remaining cents to the final eligible investor.
            # This guarantees the allocations add up exactly to the pool.
            last = investors[-1]
            last_amount = available - allocated_total

            if last_amount > 0:
                allocations.append((last, last_amount))

            # Store allocation records and deduct the distributed balance.
            records = []

            for item, amount in allocations:
                record = InvestorShareAllocation(
                    investor_id=item["investor_id"],
                    share_pool=share_pool,
                    amount=amount,
                    contribution_basis=item["total"],
                    total_contributions_basis=total_contributions,
                )
                record.full_clean()
                record.save()
                records.append(record)

            share_pool.share_pool_value = Decimal("0.00")
            share_pool.save(update_fields=[
                "share_pool_value",
                "updated_at",
            ])

        self.refresh_from_db()
        return records


    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(share_pool_value__gte=0),
                name="investor_share_pool_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Investor Share Pool: {self.share_pool_value}"



class SharePoolDistribution(models.Model):
    """Records the distribution of an individual profit."""

    profit = models.OneToOneField(
        ProfitTrade,
        on_delete=models.PROTECT,
        related_name="distribution",
    )

    vault = models.ForeignKey(
        VaultEquity,
        on_delete=models.PROTECT,
        related_name="profit_distributions",
    )

    share_pool = models.ForeignKey(
        InvestorSharePool,
        on_delete=models.PROTECT,
        related_name="distributions",
    )

    total_profit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    reinvestment_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    investor_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    distribution_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-distribution_date"]

    def clean(self):
        super().clean()

        if self.total_profit != (
            self.reinvestment_amount + self.investor_amount
        ):
            raise ValidationError(
                "Distribution amounts must equal the total profit."
            )

        if min(
            self.total_profit,
            self.reinvestment_amount,
            self.investor_amount,
        ) < Decimal("0.00"):
            raise ValidationError("Distribution amounts cannot be negative.")

    def __str__(self):
        return f"Distribution of {self.total_profit}"

    
class InvestorInfo(models.Model):
    investor_name = models.CharField(max_length=255)
    investor_email = models.EmailField(unique=True)
    investor_phone = models.CharField(max_length=30)

    # Cumulative capital contributed by this investor.
    investor_investment = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    join_date = models.DateTimeField(auto_now_add=True)

    def contribute_to_vault(self, vault, amount):
        """Record a contribution and add it to company equity."""

        amount = Decimal(str(amount)).quantize(Decimal("0.01"))

        if amount <= Decimal("0.00"):
            raise ValidationError(
                "Contribution must be greater than zero."
            )

        if self.pk is None or vault.pk is None:
            raise ValidationError(
                "Save the investor and vault before recording a contribution."
            )

        with transaction.atomic():
            investor = InvestorInfo.objects.select_for_update().get(
                pk=self.pk
            )

            company_vault = VaultEquity.objects.select_for_update().get(
                pk=vault.pk
            )

            investor.investor_investment += amount
            company_vault.vault_equity_value += amount

            investor.save(update_fields=["investor_investment"])
            company_vault.save(update_fields=[
                "vault_equity_value",
                "updated_at",
            ])

            contribution = InvestorContribution(
                investor=investor,
                vault=company_vault,
                amount=amount,
            )
            contribution.full_clean()
            contribution.save()

        self.refresh_from_db()
        vault.refresh_from_db()

        return contribution

    def __str__(self):
        return self.investor_name



class InvestorContribution(models.Model):
    """Historical record of each investor deposit."""

    investor = models.ForeignKey(
        InvestorInfo,
        on_delete=models.PROTECT,
        related_name="contributions",
    )

    vault = models.ForeignKey(
        VaultEquity,
        on_delete=models.PROTECT,
        related_name="investor_contributions",
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    contribution_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-contribution_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="investor_contribution_amount_positive",
            ),
        ]

    def clean(self):
        super().clean()

        if self.amount is not None and self.amount <= Decimal("0.00"):
            raise ValidationError(
                {"amount": "Contribution must be greater than zero."}
            )

    def __str__(self):
        return (
            f"{self.investor.investor_name}: "
            f"{self.amount}"
        )



class InvestorShareAllocation(models.Model):
    """Records an investor's allocated share of a pool distribution."""

    investor = models.ForeignKey(
        InvestorInfo,
        on_delete=models.PROTECT,
        related_name="share_allocations",
    )

    share_pool = models.ForeignKey(
        InvestorSharePool,
        on_delete=models.PROTECT,
        related_name="allocations",
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    contribution_basis = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Investor's cumulative contributions at allocation time.",
    )

    total_contributions_basis = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Total eligible investor contributions at allocation time.",
    )

    distribution_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-distribution_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="investor_share_allocation_positive",
            ),
            models.CheckConstraint(
                condition=Q(contribution_basis__gt=0),
                name="investor_allocation_basis_positive",
            ),
            models.CheckConstraint(
                condition=Q(total_contributions_basis__gt=0),
                name="investor_total_basis_positive",
            ),
        ]

    def __str__(self):
        return f"{self.investor.investor_name}: {self.amount}"
