import os
import sys
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hebrewtool.settings")
import django
django.setup()
from django.core.cache import cache
cache.clear()
print("Cache cleared!")
