from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import include

from . import views

urlpatterns = [

    path('RBT/translate/', views.translate, name='rbt_translate'),
    path("add-commentary/", views.add_ai_commentary, name="add_ai_commentary"),
    path('RBT/edit_search/', views.edit_search, name='edit_search'),
    path('RBT/edit_footnote/', views.edit_footnote, name='edit_footnote'),
    path('RBT/edit/', views.edit, name='edit'),
    path('translate/', views.translate, name='translate'),
    path('find_replace_genesis/', views.find_replace_genesis, name='find_replace'),
    path('find_and_replace_nt/', views.find_and_replace_nt, name='find_and_replace_nt'),
    path('find_and_replace_ot/', views.find_and_replace_ot, name='find_and_replace_ot'),
    path('undo_replacements/', views.undo_replacements_view, name='undo_replacements'),
    path('search_footnotes/', views.search_footnotes, name='search_footnotes'),
    path('edit_footnote/', views.edit_footnote, name='edit_footnote'),
    path('edit/', views.edit, name='edit'),
    path('edit_nt_chapter/', views.edit_nt_chapter, name='edit_nt_chapter'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('chapter_editor/', views.chapter_editor, name='chapter_editor'),
    path('', views.translate, name='translate'),

]