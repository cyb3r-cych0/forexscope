"""
URL configuration for forexscope project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""


from django.contrib import admin
from django.urls import path, include  # <-- Make sure 'include' is imported
from analytics import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('analytics.urls')),  # <-- Routes empty path requests to your app
    path('accounts/', include('django.contrib.auth.urls'))
]


# from django.contrib import admin
# from django.urls import path, include
# from analytics import views

# urlpatterns = [

#     path('wallet_dashboard/', views.wallet_dashboard, name='wallet_dashboard'),
#     path('vault/<int:vault_id>/add-equity/', views.add_equity_view, name='add_equity'),
#     path('vault/<int:vault_id>/transfer/', views.transfer_to_pool_view, name='transfer_to_pool'),
#     path('pool/<int:pool_id>/record-profit/', views.record_profit_trade_view, name='record_profit_trade'),
#     path('pool/<int:pool_id>/record-loss/', views.record_loss_trade_view, name='record_loss_trade'),
    
# ]
