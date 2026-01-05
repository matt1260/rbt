from django.urls import path

from . import views

urlpatterns = [
    path('', views.search, name='search'),
    path('search/', views.search, name='search'),
    path('search/results/', views.search_results_page, name='search_results'),
    path('RBT/search/word/', views.word_view, name='word'),
    path('search/word/', views.word_view, name='word'),
    path('aseneth/', views.storehouse_view, name='storehouse'),
    path('updates/', views.updates, name='updates'),
    path('update_count/', views.update_count, name='update_count_api'),
    path('statistics/', views.update_statistics_view, name='update_statistics'),
    path('stats/', views.update_statistics_api, name='update_statistics_api'),
    
    # Search API endpoints (note: base URL is already /api/ from main urls.py)
    path('live/', views.search_api, name='search_api'),
    path('suggest/', views.search_suggestions, name='search_suggestions'),
]