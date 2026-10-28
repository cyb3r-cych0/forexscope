from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import View
from django.utils import timezone
from django.db.models import Sum, Count
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
    vault = VaultEquity.objects.filter(user=request.user).first()
    pool = TradingPool.objects.filter(user=request.user).first()
    share = InvestorSharePool.objects.filter(user=request.user).first()

    # Only count contributions to this user's company vaults.
    contributions = InvestorContribution.objects.filter(
        vault__user=request.user
    )

    investor_stats = contributions.aggregate(
        total_i=Sum("amount"),
        count_i=Count("investor", distinct=True),
    )

    profit_stats = ProfitTrade.objects.filter(
        user=request.user
    ).aggregate(
        total_p=Sum("profit_value"),
        count_p=Count("id"),
    )

    loss_stats = LossTrade.objects.filter(
        user=request.user
    ).aggregate(
        total_l=Sum("loss_value"),
        count_l=Count("id"),
    )

    gross_profit = profit_stats["total_p"] or Decimal("0.00")
    gross_loss = loss_stats["total_l"] or Decimal("0.00")

    win_count = profit_stats["count_p"] or 0
    loss_count = loss_stats["count_l"] or 0
    total_trades = win_count + loss_count

    gross_investment = investor_stats["total_i"] or Decimal("0.00")
    investors_count = investor_stats["count_i"] or 0

    win_rate = (
        (win_count / total_trades) * 100
        if total_trades else 0
    )

    net_profit = gross_profit - gross_loss

    avg_profit = (
        gross_profit / win_count
        if win_count else Decimal("0.00")
    )
    avg_loss = (
        gross_loss / loss_count
        if loss_count else Decimal("0.00")
    )

    profit_loss_ratio = (
        avg_profit / avg_loss
        if avg_loss > 0
        else Decimal("0.00")
    )

    # Distributions belonging to this user's trading activity.
    distributions = SharePoolDistribution.objects.filter(
        profit__user=request.user
    ).select_related("profit", "vault", "share_pool")

    total_reinvested = distributions.aggregate(
        total=Sum("reinvestment_amount")
    )["total"] or Decimal("0.00")

    total_investor_allocated = distributions.aggregate(
        total=Sum("investor_amount")
    )["total"] or Decimal("0.00")

    context = {
        "vault": vault,
        "pool": pool,
        "share": share,
        "gross_investment": gross_investment,
        "investors_count": investors_count,
        "total_reinvested": total_reinvested,
        "total_investor_allocated": total_investor_allocated,
        "stats": {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 1),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "net_profit": net_profit,
        },
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



# @login_required
# def investor_share_pool_view(request):
#     """
#     Display the investor share pool and allocate its balance
#     when the user submits the distribution form.
#     """

#     share_pool = InvestorSharePool.objects.filter(
#         user=request.user
#     ).first()

#     if request.method == "POST":
#         if share_pool is None:
#             messages.error(
#                 request,
#                 "Your investor share pool has not been created yet.",
#             )
#             return redirect("investor_share_pool")

#         try:
#             # The model method performs the allocation transaction.
#             allocations = share_pool.distribute_to_investors()

#             messages.success(
#                 request,
#                 f"Successfully allocated shares to {len(allocations)} "
#                 "investor allocation record(s).",
#             )

#         except ValidationError as exc:
#             for error in getattr(exc, "messages", [str(exc)]):
#                 messages.error(request, error)

#         return redirect("investor_share_pool")

#     allocations = InvestorShareAllocation.objects.filter(
#         share_pool__user=request.user
#     ).select_related("investor", "share_pool")

#     contributions = InvestorContribution.objects.filter(
#         vault__user=request.user
#     )

#     contribution_total = contributions.aggregate(
#         total=Sum("amount")
#     )["total"] or Decimal("0.00")

#     allocation_total = allocations.aggregate(
#         total=Sum("amount")
#     )["total"] or Decimal("0.00")

#     context = {
#         "share_pool": share_pool,
#         "allocations": allocations,
#         "contribution_total": contribution_total,
#         "allocation_total": allocation_total,
#     }

#     return render(
#         request,
#         "investor_share_pool.html",
#         context,
#     )



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
