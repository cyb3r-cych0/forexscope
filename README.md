# ForexScope

ForexScope is a Django-based finance and trading analytics prototype built to track investor funding, trading activity, capital pools, and profit distribution. The project models a company or portfolio operation where investors fund a vault, capital is moved into a trading pool, trades generate profit/loss records, and investor allocations are calculated from the share pool.

## Overview

This application is designed for a finance workflow that includes:

- Investor registration and contribution tracking
- Vault equity management and transaction history
- Trading pool balances and fund transfers
- Profit and loss trade logging
- Distribution of trading gains between the vault and investor share pool
- Dashboard analytics showing performance trends and key metrics

The project is currently structured as a Django app named `analytics` inside a project package named `forexscope`.

## Tech Stack

- Python 3
- Django 6.1.2
- SQLite (default development database)
- Bootstrap 5 via `django-crispy-forms` and `crispy-bootstrap5`
- Asset compression via `django-compressor`

## Repository Structure

```text
app/
├── README.md
├── requirements.txt
└── forexscope/
    ├── analytics/
    │   ├── admin.py
    │   ├── apps.py
    │   ├── forms.py
    │   ├── models.py
    │   ├── tests.py
    │   ├── urls.py
    │   └── views.py
    ├── forexscope/
    │   ├── __init__.py
    │   ├── settings.py
    │   ├── urls.py
    │   ├── wsgi.py
    │   └── asgi.py
    └── manage.py
```

## Core Features

### Investor and vault management

- `InvestorInfo` stores investor profile details and cumulative investment value
- `InvestorContribution` records each deposit into the company vault
- `VaultEquity` tracks the current cash available in the company vault
- `VaultTransaction` logs funding and withdrawal entries with balance snapshots

### Trading pool operations

- `TradingPool` represents a company trading allocation
- Funds can be transferred from the vault to the trading pool
- `ProfitTrade` and `LossTrade` records track each trade outcome
- `PoolTransfer` provides a transaction audit trail for vault-to-pool transfers

### Profit distribution logic

- Successful profits are split between:
  - reinvestment back into the vault
  - investor share pool allocation
- `SharePoolDistribution` records how a profit was divided
- `InvestorSharePool` holds funds earmarked for investors
- `InvestorShareAllocation` calculates each investor's share proportionally to their contribution basis

### Analytics dashboard

The `wallet_dashboard` view aggregates:

- current vault and pool balances
- recent profit and loss activity
- monthly profit/loss trends
- win/loss statistics
- investor contribution totals
- investor distribution totals

## Getting Started

### 1. Create a virtual environment

```bash
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

From the project root (`app/`):

```bash
pip install -r requirements.txt
```

### 3. Apply database migrations

```bash
cd forexscope
python manage.py migrate
```

### 4. Create an admin user

```bash
python manage.py createsuperuser
```

### 5. Run the development server

```bash
python manage.py runserver
```

Then open:

- http://127.0.0.1:8000/
- http://127.0.0.1:8000/admin/

## Main Routes

The app routes are defined in `analytics/urls.py` and include:

- `/` → home page
- `/dashboard/` → wallet dashboard and analytics view
- `/wallet/create/<resource>/` → create vault or trading resources
- `/vault/<id>/add-equity/` → add funds to a vault
- `/vault/<id>/transfer/` → move funds into trading pool
- `/pool/<id>/record-trade/` → trade logging flow
- `/registration/register_investor/` → investor registration
- `/investors/investor-share-pool/` → investor share pool actions
- `/analytics/stats_dashboard/` → stats dashboard

## Configuration Notes

- The default project uses SQLite for local development.
- `DEBUG = True` is enabled in `forexscope/settings.py`, which is appropriate for a prototype but not for production.
- `LOGIN_REDIRECT_URL` is configured to `/dashboard/`.

## Project Status

This repository is a prototype / MVP implementation for a finance-tracking and trading analytics system. It is not a production-ready deployment stack and may still require validation, security hardening, and additional business rules before use in a live environment.

## License
