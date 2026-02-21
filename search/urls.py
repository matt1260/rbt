from django.urls import path

from . import views

urlpatterns = [
    path('', views.search, name='search'),
    path('search/', views.search, name='search'),
    path('search/results/', views.search_results_page, name='search_results'),
    path('aseneth/', views.storehouse_view, name='storehouse'),
    path('storehouse/', views.storehouse_view, name='storehouse'),
    path('updates/', views.updates, name='updates'),
    path('update_count/', views.update_count, name='update_count_api'),
    path('statistics/', views.update_statistics_view, name='update_statistics'),
    path('stats/', views.update_statistics_api, name='update_statistics_api'),
    path('visitor_locations/', views.visitor_locations_api, name='visitor_locations_api'),
    
    # Footnote JSON API for popup display
    path('footnote/<str:footnote_id>/json/', views.footnote_json, name='footnote_json'),
    
    # Search API endpoints (note: base URL is already /api/ from main urls.py)
    path('live/', views.search_api, name='search_api'),
    path('suggest/', views.search_suggestions, name='search_suggestions'),
    path('translate_chapter/', views.translate_chapter_api, name='translate_chapter_api'),
    
    # Background translation job API endpoints
    path('translation/start/', views.start_translation_job, name='start_translation_job'),
    path('translation/status/', views.translation_job_status, name='translation_job_status'),
    path('translation/clear-cache/', views.clear_translation_cache, name='clear_translation_cache'),
    path('translation/retry-failed/', views.retry_failed_translations, name='retry_failed_translations'),
]