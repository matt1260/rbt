from django.urls import path

from . import views

urlpatterns = [
    path('', views.lexicon_root_redirect, name='lexicon_root'),
    path('hebrew/', views.lexicon_index, name='lexicon_index'),
    path('hebrew/search/', views.lexicon_search, name='lexicon_search'),
    path('hebrew/<str:strongs>/', views.lexicon_word_detail, name='lexicon_word_detail'),
]
