from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import include

from . import views

urlpatterns = [

    path('RBT/translate/', views.translate, name='rbt_translate'),
    path("edit_nt_chapter/", views.edit_nt_chapter, name="edit_nt_chapter"),
    path('RBT/edit_search/', views.edit_search, name='edit_search'),
    path('RBT/edit_footnote/', views.edit_footnote, name='edit_footnote'),
    path('RBT/edit/', views.edit, name='edit'),
    path('translate/', views.translate, name='translate'),
    path('find_replace_genesis/', views.find_replace_genesis, name='find_replace'),
    path('find_and_replace_nt/', views.find_and_replace_nt, name='find_and_replace_nt'),
    path('find_and_replace_ot/', views.find_and_replace_ot, name='find_and_replace_ot'),
    path('gemini/translate/', views.request_gemini_translation, name='gemini_translate_api'),
    path('gemini/preferences/', views.save_gemini_preferences, name='gemini_save_preferences'),
    path('undo_replacements/', views.undo_replacements_view, name='undo_replacements'),
    path('search_footnotes/', views.search_footnotes, name='search_footnotes'),
    path('edit_footnote/', views.edit_footnote, name='edit_footnote'),
    path('edit/', views.edit, name='edit'),
    path('edit_nt_chapter/', views.edit_nt_chapter, name='edit_nt_chapter'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('chapter_editor/', views.chapter_editor, name='chapter_editor'),
    path('api/add-manual-lexicon-mapping/', views.add_manual_lexicon_mapping, name='add_manual_lexicon_mapping'),
    path('api/get-lexicon-strongs/', views.get_lexicon_strongs, name='get_lexicon_strongs'),
    path('api/update-lexicon-entry/', views.update_lexicon_entry, name='update_lexicon_entry'),
    path('api/search-lexicon/', views.get_lexicon_search_results, name='search_lexicon'),
    path('api/search-consonantal/', views.search_consonantal, name='search_consonantal'),
    path('api/update-interlinear-word/', views.update_interlinear_word, name='update_interlinear_word'),
    path('', views.translate, name='translate'),

]