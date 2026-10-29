from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),  # Maps the root of the app to the home view
    path('dashboard/', views.wallet_dashboard, name='wallet_dashboard'),
    path('pool/<int:pool_id>/record-trade/', views.record_trade_view, name='record_trade'),
    path('wallet/create/<str:resource>/', views.create_wallet_resource, name='create_wallet_resource'),
    path('vault/<int:vault_id>/add-equity/', views.add_equity_view, name='add_equity'),
    path('vault/<int:vault_id>/transfer/', views.transfer_to_pool_view, name='transfer_to_pool'),
    path('registration/register_investor/',views.RegisterInvestor.as_view(),name='register_investor'),
    path("investor-share-pool/", views.investor_share_pool_view, name="investor_share_pool",),
    
]
