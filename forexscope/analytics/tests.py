from django.test import TestCase
from django.contrib.auth.models import User

from .models import TradingPool, VaultEquity


class WalletDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="wallet-user", password="test-password")
        self.client.force_login(self.user)

    def test_dashboard_renders_without_trading_pool(self):
        response = self.client.get("/wallet_dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trade logging is unavailable until a trading pool is active.")

    def test_dashboard_shows_trade_forms_when_pool_exists(self):
        pool = TradingPool.objects.create(user=self.user)

        response = self.client.get("/wallet_dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"/pool/{pool.pk}/record-profit/")
        self.assertContains(response, f"/pool/{pool.pk}/record-loss/")

    def test_dashboard_shows_create_buttons_when_resources_are_missing(self):
        response = self.client.get("/wallet_dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Vault")
        self.assertContains(response, "Create Trading Pool")

    def test_create_vault_and_trading_pool(self):
        vault_response = self.client.post("/wallet/create/vault/")
        pool_response = self.client.post("/wallet/create/trading-pool/")

        self.assertRedirects(vault_response, "/wallet_dashboard/")
        self.assertRedirects(pool_response, "/wallet_dashboard/")
        self.assertTrue(VaultEquity.objects.filter(user=self.user).exists())
        self.assertTrue(TradingPool.objects.filter(user=self.user).exists())

    def test_create_wallet_resource_does_not_duplicate_existing_records(self):
        VaultEquity.objects.create(user=self.user)

        self.client.post("/wallet/create/vault/")

        self.assertEqual(VaultEquity.objects.filter(user=self.user).count(), 1)

    def test_create_wallet_resource_requires_post(self):
        response = self.client.get("/wallet/create/vault/")

        self.assertEqual(response.status_code, 405)
