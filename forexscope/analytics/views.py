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
from .models import VaultEquity, TradingPool, PoolTransfer, ProfitTrade, LossTrade


def home(request):
    return render(request, 'home.html')

# @login_required
# def wallet_dashboard(request):
    # Fetch data for the logged-in user
    vault = VaultEquity.objects.filter(user=request.user).first()
    pool = TradingPool.objects.filter(user=request.user).first()

    context = {
        'vault': vault,
        'pool': pool,
    }
    return render(request, 'wallet_dashboard.html', context)

@login_required
def wallet_dashboard(request):
    vault = VaultEquity.objects.filter(user=request.user).first()
    pool = TradingPool.objects.filter(user=request.user).first()
    
    # 1. Gather raw statistics metrics from the database
    profit_stats = ProfitTrade.objects.filter(user=request.user).aggregate(
        total_p=Sum('profit_value'),
        count_p=Count('id')
    )
    loss_stats = LossTrade.objects.filter(user=request.user).aggregate(
        total_l=Sum('loss_value'),
        count_l=Count('id')
    )

    gross_profit = profit_stats['total_p'] or Decimal('0.00')
    gross_loss = loss_stats['total_l'] or Decimal('0.00')
    win_count = profit_stats['count_p'] or 0
    loss_count = loss_stats['count_l'] or 0
    total_trades = win_count + loss_count

    # 2. Calculate real-time indicators safely avoiding zero divisions
    win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
    net_profit = gross_profit - gross_loss
    
    avg_profit = gross_profit / win_count if win_count > 0 else Decimal('0.00')
    avg_loss = gross_loss / loss_count if loss_count > 0 else Decimal('0.00')
    profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else (gross_profit if gross_profit > 0 else Decimal('0.00'))

    context = {
        'vault': vault,
        'pool': pool,
        'stats': {
            'total_trades': total_trades,
            'win_rate': round(win_rate, 1),
            'profit_loss_ratio': round(profit_loss_ratio, 2),
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'net_profit': net_profit,
        }
    }
    return render(request, 'wallet_dashboard.html', context)


@login_required
def record_trade_view(request, pool_id):
    if request.method != "POST":
        return redirect('wallet_dashboard')
        
    trading_pool = get_object_or_404(TradingPool, pk=pool_id, user=request.user)
    
    # Extract values from unified parameters
    result_type = request.POST.get('result_type') # Expected: 'PROFIT' or 'LOSS'
    utility_traded = request.POST.get('utility_traded')
    trade_direction = request.POST.get('trade_direction')
    amount_raw = request.POST.get('amount', '0.00')
    description = request.POST.get('description', '').strip()
    
    try:
        amount = Decimal(str(amount_raw)).quantize(Decimal("0.01"))
        if amount <= Decimal("0.00"):
            messages.error(request, "Trade execution value must be greater than zero.")
            return redirect('wallet_dashboard')
            
        with transaction.atomic():
            pool = TradingPool.objects.select_for_update().get(pk=trading_pool.pk)
            
            if result_type == "PROFIT":
                ProfitTrade.objects.create(
                    user=request.user, trading_pool=pool, utility_traded=utility_traded,
                    trade_direction=trade_direction, profit_value=amount, description=description
                )
                pool.trading_pool_value += amount
                pool.save(update_fields=['trading_pool_value', 'updated_at'])
                messages.success(request, f"Logged trade profit of ${amount} for {utility_traded}.")
                
            elif result_type == "LOSS":
                if pool.trading_pool_value < amount:
                    messages.error(request, f"Deduction rejected. Insufficient pool allocation (${pool.trading_pool_value}).")
                    return redirect('wallet_dashboard')
                    
                LossTrade.objects.create(
                    user=request.user, trading_pool=pool, utility_traded=utility_traded,
                    trade_direction=trade_direction, loss_value=amount, description=description
                )
                pool.trading_pool_value -= amount
                pool.save(update_fields=['trading_pool_value', 'updated_at'])
                messages.success(request, f"Logged trade loss of ${amount} for {utility_traded}.")
            else:
                messages.error(request, "Invalid result selector target context.")
                
    except (InvalidOperation, ValueError):
        messages.error(request, "Numeric verification error. Check form entries.")
        
    return redirect('wallet_dashboard')


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

def add_equity_view(request, vault_id):
    if request.method == "POST":
        vault = get_object_or_404(VaultEquity, pk=vault_id, user=request.user)
        amount = request.POST.get('amount', 0)

        try:
            vault.add_equity(amount)
            messages.success(request, f"Successfully added ${amount} to your vault.")
        except ValidationError as e:
            messages.error(request, e.message)

    return redirect('wallet_dashboard')

@login_required
def transfer_to_pool_view(request, vault_id):
    if request.method == "POST":
        vault = get_object_or_404(VaultEquity, pk=vault_id, user=request.user)
        # Fetch the user's trading pool
        pool = get_object_or_404(TradingPool, user=request.user)
        amount = request.POST.get('amount', 0)

        try:
            vault.transfer_to_trading_pool(pool, amount)
            messages.success(request, f"Successfully transferred ${amount} to your Trading Pool.")
        except ValidationError as e:
            messages.error(request, e.message)

    return redirect('wallet_dashboard')


# def record_profit_trade_view(request, pool_id):
    if request.method == "POST":
        # Ensure the pool belongs to the logged-in user
        trading_pool = get_object_or_404(TradingPool, pk=pool_id, user=request.user)

        # Extract form parameters
        utility_traded = request.POST.get('utility_traded')
        trade_direction = request.POST.get('trade_direction')
        profit_value_raw = request.POST.get('profit_value', '0.00')
        description = request.POST.get('description', '').strip()

        try:
            # Convert and sanitize the numeric input
            profit_value = Decimal(str(profit_value_raw)).quantize(Decimal("0.01"))

            if profit_value <= Decimal("0.00"):
                messages.error(request, "Profit value must be greater than zero.")
                return redirect('wallet_dashboard')

            # Perform atomic updates to maintain data integrity
            with transaction.atomic():
                # Lock the specific trading pool row during update
                pool_to_update = TradingPool.objects.select_for_update().get(pk=trading_pool.pk)

                # 1. Create the permanent trade log entry
                ProfitTrade.objects.create(
                    user=request.user,
                    trading_pool=pool_to_update,
                    utility_traded=utility_traded,
                    trade_direction=trade_direction,
                    profit_value=profit_value,
                    description=description
                )

                # 2. Add the profit directly to the trading pool balance
                pool_to_update.trading_pool_value += profit_value
                pool_to_update.save(update_fields=['trading_pool_value', 'updated_at'])

            messages.success(request, f"Successfully recorded profit of ${profit_value} for {utility_traded}.")

        except (InvalidOperation, ValueError):
            messages.error(request, "Invalid numeric format provided for profit value.")
        except Exception as e:
            messages.error(request, f"An unexpected error occurred: {str(e)}")

    return redirect('wallet_dashboard')


# def record_loss_trade_view(request, pool_id):
    if request.method == "POST":
        # Confirm pool belongs to logged-in user
        trading_pool = get_object_or_404(TradingPool, pk=pool_id, user=request.user)

        # Extract parameters
        utility_traded = request.POST.get('utility_traded')
        trade_direction = request.POST.get('trade_direction')
        loss_value_raw = request.POST.get('loss_value', '0.00')
        description = request.POST.get('description', '').strip()

        try:
            # Sanitize and convert numeric input
            loss_value = Decimal(str(loss_value_raw)).quantize(Decimal("0.01"))

            if loss_value <= Decimal("0.00"):
                messages.error(request, "Loss amount must be greater than zero.")
                return redirect('wallet_dashboard')

            with transaction.atomic():
                # Lock row to prevent race conditions during verification/deduction
                pool_to_update = TradingPool.objects.select_for_update().get(pk=trading_pool.pk)

                # Enforce protection against negative trading pool balances
                if pool_to_update.trading_pool_value < loss_value:
                    messages.error(
                        request,
                        f"Insufficient funds in pool. Current balance is ${pool_to_update.trading_pool_value}, "
                        f"but tried to deduct a loss of ${loss_value}."
                    )
                    return redirect('wallet_dashboard')

                # 1. Create permanent loss ledger history entry
                LossTrade.objects.create(
                    user=request.user,
                    trading_pool=pool_to_update,
                    utility_traded=utility_traded,
                    trade_direction=trade_direction,
                    loss_value=loss_value,
                    description=description
                )

                # 2. Safely deduct the loss from active balance
                pool_to_update.trading_pool_value -= loss_value
                pool_to_update.save(update_fields=['trading_pool_value', 'updated_at'])

            messages.success(request, f"Recorded loss of ${loss_value} for {utility_traded}. Balance updated.")

        except (InvalidOperation, ValueError):
            messages.error(request, "Invalid numeric format provided for loss value.")
        except Exception as e:
            messages.error(request, f"An unexpected processing error occurred: {str(e)}")

    return redirect('wallet_dashboard')