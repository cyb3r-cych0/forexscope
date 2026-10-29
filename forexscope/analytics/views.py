import json
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import View
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from decimal import Decimal, InvalidOperation
from .forms import InvestorInfoForm
from .models import (
                    VaultEquity, TradingPool, PoolTransfer, 
                    ProfitTrade, LossTrade, SharePoolDistribution, 
                    InvestorContribution, InvestorInfo, InvestorSharePool, InvestorShareAllocation
                )


def home(request):
    return render(request, 'home.html')


@login_required
def wallet_dashboard(request):
    # --------------------------------------------------
    # 1. Current user's accounts
    # --------------------------------------------------
    vault = VaultEquity.objects.filter(user=request.user).first()
    pool = TradingPool.objects.filter(user=request.user).first()
    share = InvestorSharePool.objects.filter(user=request.user).first()

    profits = ProfitTrade.objects.filter(user=request.user)
    losses = LossTrade.objects.filter(user=request.user)

    contributions = InvestorContribution.objects.filter(
        vault__user=request.user
    )

    # Supported dashboard periods
    period_options = {
        "7": 7,
        "30": 30,
        "90": 90,
        "all": None,
    }

    selected_period = request.GET.get("period", "30")

    if selected_period not in period_options:
        selected_period = "30"

    period_days = period_options[selected_period]

    # Start with the current user's trade records.
    profits = ProfitTrade.objects.filter(user=request.user)
    losses = LossTrade.objects.filter(user=request.user)

    # Apply the selected date range to trading analytics.
    if period_days is not None:
        start_date = timezone.localdate() - timedelta(
            days=period_days - 1
        )

        profits = profits.filter(
            profit_trade_date__date__gte=start_date
        )

        losses = losses.filter(
            loss_trade_date__date__gte=start_date
        )

    # Recent profit entries
    recent_activity = []

    for trade in profits.order_by("-profit_trade_date")[:10]:
        recent_activity.append({
            "date": trade.profit_trade_date,
            "type": "PROFIT",
            "asset": trade.utility_traded,
            "direction": trade.trade_direction,
            "amount": trade.profit_value,
            "description": trade.description,
        })

    # Recent loss entries
    for trade in losses.order_by("-loss_trade_date")[:10]:
        recent_activity.append({
            "date": trade.loss_trade_date,
            "type": "LOSS",
            "asset": trade.utility_traded,
            "direction": trade.trade_direction,
            "amount": trade.loss_value,
            "description": trade.description,
        })

    # Combine both record types and retain the latest 10.
    recent_activity.sort(
        key=lambda item: item["date"],
        reverse=True,
    )

    recent_activity = recent_activity[:10]



    # --------------------------------------------------
    # 2. Main trading statistics
    # --------------------------------------------------
    profit_stats = profits.aggregate(
        total=Sum("profit_value"),
        count=Count("id"),
    )
    loss_stats = losses.aggregate(
        total=Sum("loss_value"),
        count=Count("id"),
    )

    gross_profit = profit_stats["total"] or Decimal("0.00")
    gross_loss = loss_stats["total"] or Decimal("0.00")

    win_count = profit_stats["count"] or 0
    loss_count = loss_stats["count"] or 0
    total_trades = win_count + loss_count

    net_profit = gross_profit - gross_loss

    win_rate = (
        (win_count / total_trades) * 100
        if total_trades else 0
    )

    average_profit = (
        gross_profit / win_count
        if win_count else Decimal("0.00")
    )

    average_loss = (
        gross_loss / loss_count
        if loss_count else Decimal("0.00")
    )

    profit_loss_ratio = (
        average_profit / average_loss
        if average_loss > 0 else Decimal("0.00")
    )

    # --------------------------------------------------
    # 3. Investor contribution statistics
    # --------------------------------------------------
    investor_stats = contributions.aggregate(
        total=Sum("amount"),
        count=Count("investor", distinct=True),
    )

    gross_investment = (
        investor_stats["total"] or Decimal("0.00")
    )
    investors_count = investor_stats["count"] or 0

    # --------------------------------------------------
    # 4. Profit distribution statistics
    # --------------------------------------------------
    distributions = SharePoolDistribution.objects.filter(
        profit__user=request.user
    )

    distribution_stats = distributions.aggregate(
        reinvested=Sum("reinvestment_amount"),
        allocated=Sum("investor_amount"),
    )

    total_reinvested = (
        distribution_stats["reinvested"] or Decimal("0.00")
    )
    total_investor_allocated = (
        distribution_stats["allocated"] or Decimal("0.00")
    )

    # --------------------------------------------------
    # 5. Daily profit and loss for the line chart
    # --------------------------------------------------
    daily_profits = (
        profits.annotate(day=TruncDate("profit_trade_date"))
        .values("day")
        .annotate(total=Sum("profit_value"))
        .order_by("day")
    )

    daily_losses = (
        losses.annotate(day=TruncDate("loss_trade_date"))
        .values("day")
        .annotate(total=Sum("loss_value"))
        .order_by("day")
    )

    daily_data = {}

    for row in daily_profits:
        if row["day"]:
            daily_data.setdefault(
                row["day"].isoformat(),
                {"profit": 0.0, "loss": 0.0},
            )
            daily_data[row["day"].isoformat()]["profit"] = float(
                row["total"] or 0
            )

    for row in daily_losses:
        if row["day"]:
            daily_data.setdefault(
                row["day"].isoformat(),
                {"profit": 0.0, "loss": 0.0},
            )
            daily_data[row["day"].isoformat()]["loss"] = float(
                row["total"] or 0
            )

    sorted_days = sorted(daily_data.keys())

    cumulative_net = 0.0
    cumulative_values = []
    daily_profit_values = []
    daily_loss_values = []
    daily_net_values = []

    for day in sorted_days:
        profit_value = daily_data[day]["profit"]
        loss_value = daily_data[day]["loss"]
        net_value = profit_value - loss_value

        cumulative_net += net_value

        daily_profit_values.append(profit_value)
        daily_loss_values.append(loss_value)
        daily_net_values.append(net_value)
        cumulative_values.append(round(cumulative_net, 2))

    # --------------------------------------------------
    # 6. Profit and loss by asset
    # --------------------------------------------------
    asset_profits = (
        profits.values("utility_traded")
        .annotate(total=Sum("profit_value"))
    )

    asset_losses = (
        losses.values("utility_traded")
        .annotate(total=Sum("loss_value"))
    )

    asset_data = {}

    for row in asset_profits:
        asset = row["utility_traded"] or "UNKNOWN"
        asset_data.setdefault(
            asset, {"profit": 0.0, "loss": 0.0}
        )
        asset_data[asset]["profit"] = float(row["total"] or 0)

    for row in asset_losses:
        asset = row["utility_traded"] or "UNKNOWN"
        asset_data.setdefault(
            asset, {"profit": 0.0, "loss": 0.0}
        )
        asset_data[asset]["loss"] = float(row["total"] or 0)

    # --------------------------------------------------
    # 7. Contributions by investor
    # --------------------------------------------------
    investor_contributions = (
        contributions.values(
            "investor_id",
            "investor__investor_name",
        )
        .annotate(total=Sum("amount"))
        .order_by("-total")[:10]
    )

    investor_labels = [
        row["investor__investor_name"]
        for row in investor_contributions
    ]

    investor_amounts = [
        float(row["total"] or 0)
        for row in investor_contributions
    ]

    # --------------------------------------------------
    # 8. Account balance comparison
    # --------------------------------------------------
    account_labels = [
        "Vault Equity",
        "Trading Pool",
        "Available Share Pool",
    ]

    account_values = [
        float(vault.vault_equity_value) if vault else 0.0,
        float(pool.trading_pool_value) if pool else 0.0,
        float(share.share_pool_value) if share else 0.0,
    ]

    # --------------------------------------------------
    # 9. Chart data
    # --------------------------------------------------
    chart_data = {
        "daily": {
            "labels": sorted_days,
            "profits": daily_profit_values,
            "losses": daily_loss_values,
            "net": daily_net_values,
            "cumulative": cumulative_values,
        },
        "assets": {
            "labels": list(asset_data.keys()),
            "profits": [
                values["profit"] for values in asset_data.values()
            ],
            "losses": [
                values["loss"] for values in asset_data.values()
            ],
        },
        "investors": {
            "labels": investor_labels,
            "contributions": investor_amounts,
        },
        "accounts": {
            "labels": account_labels,
            "balances": account_values,
        },
    }

    # --------------------------------------------------
    # 10. Dashboard context
    # --------------------------------------------------
    context = {
        "vault": vault,
        "pool": pool,
        "share": share,
        "gross_investment": gross_investment,
        "investors_count": investors_count,
        "total_reinvested": total_reinvested,
        "total_investor_allocated": total_investor_allocated,
        "selected_period": selected_period,
        "period_options": [
            {"value": "7", "label": "Last 7 days"},
            {"value": "30", "label": "Last 30 days"},
            {"value": "90", "label": "Last 90 days"},
            {"value": "all", "label": "All time"},
        ],
        "stats": {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "net_profit": net_profit,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "average_profit": average_profit,
            "average_loss": average_loss,
        },
        "chart_data": chart_data,
        "recent_activity": recent_activity
    }

    return render(request, "wallet_dashboard.html", context)


@login_required
@require_POST
def record_trade_view(request, pool_id):
    result_type = request.POST.get("result_type", "").strip().upper()
    utility = request.POST.get("utility_traded", "").strip()
    direction = request.POST.get("trade_direction", "").strip().upper()
    description = request.POST.get("description", "").strip()
    amount_raw = request.POST.get("amount", "").strip()

    try:
        amount = Decimal(amount_raw).quantize(Decimal("0.01"))

        if not amount.is_finite() or amount <= Decimal("0.00"):
            raise InvalidOperation("Amount must be positive.")

        # Validate the selected values against the model choices.
        valid_utilities = {
            value for value, label in ProfitTrade.TradeUtility.choices
        }
        valid_directions = {
            value for value, label in ProfitTrade.TradeDirection.choices
        }

        if utility not in valid_utilities:
            raise ValidationError("Select a valid trading instrument.")

        if direction not in valid_directions:
            raise ValidationError("Select a valid trade direction.")

        if result_type not in {"PROFIT", "LOSS"}:
            raise ValidationError("Select PROFIT or LOSS.")

        with transaction.atomic():
            pool = get_object_or_404(
                TradingPool.objects.select_for_update(),
                pk=pool_id,
                user=request.user,
            )

            if result_type == "PROFIT":
                vault = get_object_or_404(
                    VaultEquity.objects.select_for_update(),
                    user=request.user,
                )

                profit = pool.record_profit(
                    amount=amount,
                    utility=utility,
                    direction=direction,
                    description=description,
                )

                distribution = pool.distribute_profit(profit, vault)

                messages.success(
                    request,
                    (
                        f"Profit of {amount:.2f} recorded. "
                        f"{distribution.reinvestment_amount:.2f} "
                        "returned to the vault and "
                        f"{distribution.investor_amount:.2f} "
                        "added to the investor share pool."
                    ),
                )

            else:
                loss = pool.record_loss(
                    amount=amount,
                    utility=utility,
                    direction=direction,
                    description=description,
                )

                messages.success(
                    request,
                    f"Loss of {loss.loss_value:.2f} recorded successfully.",
                )

    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, "Enter a valid positive monetary amount.")

    except ValidationError as exc:
        for error in getattr(exc, "messages", [str(exc)]):
            messages.error(request, error)

    return redirect("wallet_dashboard")


@login_required
@require_POST
def create_wallet_resource(request, resource):
    resources = {
        "vault": (VaultEquity, "vault"),
        "trading-pool": (TradingPool, "trading pool"),
    }
    if resource not in resources:
        raise Http404("Unknown wallet resource.")

    model, label = resources[resource]
    _, created = model.objects.get_or_create(user=request.user)
    if created:
        messages.success(request, f"Your {label} has been created.")
    else:
        messages.info(request, f"You already have a {label}.")

    return redirect('wallet_dashboard')


@login_required
@require_POST
def add_equity_view(request, vault_id):
    vault = get_object_or_404(
        VaultEquity,
        pk=vault_id,
        user=request.user,
    )

    try:
        amount = Decimal(request.POST.get("amount", "").strip())
        vault.add_equity(amount)

        messages.success(
            request,
            f"Successfully added {amount:.2f} to your vault.",
        )

    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, "Enter a valid monetary amount.")

    except ValidationError as exc:
        for error in getattr(exc, "messages", [str(exc)]):
            messages.error(request, error)

    return redirect("wallet_dashboard")


@login_required
@require_POST
def transfer_to_pool_view(request, vault_id):
    vault = get_object_or_404(
        VaultEquity,
        pk=vault_id,
        user=request.user,
    )

    pool = TradingPool.objects.filter(
        user=request.user
    ).first()

    if pool is None:
        messages.error(
            request,
            "Create your trading pool before transferring funds.",
        )
        return redirect("wallet_dashboard")

    try:
        amount = Decimal(request.POST.get("amount", "").strip())
        vault.transfer_to_trading_pool(pool, amount)

        messages.success(
            request,
            f"Successfully transferred {amount:.2f} to the trading pool.",
        )

    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, "Enter a valid monetary amount.")

    except ValidationError as exc:
        for error in getattr(exc, "messages", [str(exc)]):
            messages.error(request, error)

    return redirect("wallet_dashboard")


class RegisterInvestor(View):

    @staticmethod
    def get(request):
        form = InvestorInfoForm()

        return render(
            request,
            "registration/register_investor.html",
            {"form": form},
        )

    @staticmethod
    def post(request):
        form = InvestorInfoForm(request.POST)

        if not form.is_valid():
            messages.error(
                request,
                "Registration unsuccessful. Please correct the errors below.",
            )
            return render(
                request,
                "registration/register_investor.html",
                {"form": form},
            )

        amount = form.cleaned_data["investor_investment"]
        username = form.cleaned_data["investor_name"]

        try:
            with transaction.atomic():

                # Validate the investment amount.
                amount = Decimal(str(amount)).quantize(Decimal("0.01"))

                if not amount.is_finite() or amount <= Decimal("0.00"):
                    raise ValidationError(
                        "The initial investment must be greater than zero."
                    )

                # Obtain or create the authenticated user's company vault.
                # The contribution method handles locking and balance updates.
                vault, _ = VaultEquity.objects.get_or_create(
                    user=request.user
                )

                # Create the investor without applying the initial investment
                # directly, because contribute_to_vault() applies it.
                investor = form.save(commit=False)
                investor.investor_investment = Decimal("0.00")
                investor.save()

                # Update the investor's cumulative investment, credit the
                # vault, and create the InvestorContribution history record.
                contribution = investor.contribute_to_vault(
                    vault=vault,
                    amount=amount,
                )

                messages.success(
                    request,
                    (
                        f"Investor {username} registered successfully. "
                        f"Initial investment: ${amount:.2f}. "
                        "The investment has been credited to the vault."
                    ),
                )

        except ValidationError as exc:
            for error in getattr(exc, "messages", [str(exc)]):
                messages.error(request, error)

        except Exception:
            # The atomic transaction rolls back database changes if an
            # exception occurs. Avoid exposing internal exception details.
            messages.error(
                request,
                "Investor registration failed. No investment was recorded.",
            )

        return redirect("wallet_dashboard")


@login_required
def investor_share_pool_view(request):
    share_pool = InvestorSharePool.objects.filter(
        user=request.user
    ).first()

    # Only allow allocation through POST.
    if request.method == "POST":
        if share_pool is None:
            messages.error(
                request,
                "The investor share pool does not exist yet."
            )
            return redirect("investor_share_pool")

        try:
            allocations = share_pool.distribute_to_investors()

            messages.success(
                request,
                f"Allocation completed. "
                f"{len(allocations)} investor allocation record(s) created."
            )

        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)

        return redirect("investor_share_pool")

    # Only show contributions belonging to this user's vault.
    contributions = InvestorContribution.objects.filter(
        vault__user=request.user
    )

    contribution_total = (
        contributions.aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    # Show allocation records for this user's share pool only.
    allocations = InvestorShareAllocation.objects.filter(
        share_pool__user=request.user
    ).select_related(
        "investor",
        "share_pool",
    ).order_by("-distribution_date")

    allocation_total = (
        allocations.aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    context = {
        "share_pool": share_pool,
        "contribution_total": contribution_total,
        "allocation_total": allocation_total,
        "allocations": allocations,
    }

    return render(
        request,
        "investor_share_pool.html",
        context,
    )
