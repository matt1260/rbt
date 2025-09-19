from django.urls import path

from . import views

urlpatterns = [
    path('', views.search, name='search'),
    path('search/', views.search, name='search'),
    path('RBT/search/word/', views.word_view, name='word'),
    path('search/word/', views.word_view, name='word'),
    path('updates/', views.updates, name='updates'),
    path('update_count/', views.update_count, name='update_count_api'),
    path('statistics/', views.update_statistics_view, name='update_statistics'),
    path('stats/', views.update_statistics_api, name='update_statistics_api'),

]