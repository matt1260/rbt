"""hebrewtool URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
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
from django.urls import include, path
from django.contrib.auth import views as auth_views
from django.http import HttpResponse

from translate import views
from search.views import update_count
from .human_verification import human_challenge, human_verify

def health_check(request):
    return HttpResponse("OK", content_type="text/plain")

urlpatterns = [
    path('health', health_check, name='health_check'),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('api/', include('search.urls')),
    path('update_count/', update_count, name='update_count'),
    path('edit/accounts/', include('django.contrib.auth.urls')),
    path('edit_nt_chapter/accounts/', include('django.contrib.auth.urls')),
    path('translate/accounts/', include('django.contrib.auth.urls')),
    path('translate/update-hebrew-data/accounts/', include('django.contrib.auth.urls')),
    path('update-hebrew-data/', views.update_hebrew_data, name='update_hebrew_data'),
    path('find_and_replace_nt/', views.find_and_replace_nt, name='find_and_replace_nt'),
    path('find_and_replace_nt/accounts/', include('django.contrib.auth.urls')),
    path('find_and_replace_ot', views.find_and_replace_ot, name='find_and_replace_ot'),
    path('find_and_replace_ot/accounts/', include('django.contrib.auth.urls')),
    path('lexicon/<str:lexicon_type>/<str:page>', views.lexicon_viewer, name='lexicon_viewer'),
    path('translate/', include('translate.urls')),
    path('search_footnotes/', views.search_footnotes, name='search_footnotes'),
    path('edit_footnote/', views.edit_footnote, name='edit_footnote'),
    path('edit_search/', views.edit_search, name='edit_search'),
    path('edit/', views.edit, name='edit'),
    path('edit_nt_chapter/', views.edit_nt_chapter, name='edit_nt_chapter'),
    path('paraphrase/', include('search.urls')),
    path("edit_nt_chapter/", views.edit_nt_chapter, name="edit_nt_chapter"),
    path('RBT/', include('search.urls')),
    path('', include('search.urls')),
    path('chapter_editor/', views.chapter_editor, name='chapter_editor'),
    # Human verification endpoints used for lightweight bot challenge flow
    path('__human_challenge/', human_challenge, name='human_challenge'),
    path('__human_verify/', human_verify, name='human_verify'),
    path('edit_aseneth/', views.edit_aseneth, name='edit_aseneth'),
    path('edit_aseneth/accounts/', include('django.contrib.auth.urls')),

]

# urlpatterns = [
#     path('', include('search.urls')),
#     path('RBT/', include('search.urls')),
#     path('translate/', include('translate.urls')),
#     path('RBT/translate/', include('translate.urls')),
#     path('RBT/paraphrase/', include('search.urls')),
#     path('edit/', views.edit, name='edit'),
#     path('RBT/edit/', views.edit, name='edit'),
#     path('edit_footnote/', views.edit_footnote, name='edit_footnote'),
#     path('RBT/edit_footnote/', views.edit_footnote, name='edit_footnote'),
#     path('RBT/edit_search/', views.edit_search, name='edit_search'),
#     path('admin/', admin.site.urls),
#     path('accounts/', include('django.contrib.auth.urls')),
#     path('RBT/edit/accounts/', include('django.contrib.auth.urls')),
#     path('edit/accounts/', include('django.contrib.auth.urls')),
#     path('RBT/translate/accounts/', include('django.contrib.auth.urls')),

# ]