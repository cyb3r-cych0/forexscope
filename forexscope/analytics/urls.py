from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),  # Maps the root of the app to the home view
    path('wallet_dashboard/', views.wallet_dashboard, name='wallet_dashboard'),
    path('wallet/create/<str:resource>/', views.create_wallet_resource, name='create_wallet_resource'),
    path('vault/<int:vault_id>/add-equity/', views.add_equity_view, name='add_equity'),
    path('vault/<int:vault_id>/transfer/', views.transfer_to_pool_view, name='transfer_to_pool'),
    path('pool/<int:pool_id>/record-profit/', views.record_profit_trade_view, name='record_profit_trade'),
    path('pool/<int:pool_id>/record-loss/', views.record_loss_trade_view, name='record_loss_trade'),
    
]
