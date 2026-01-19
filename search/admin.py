from django.contrib import admin
from .models import InterlinearConfig

@admin.register(InterlinearConfig)
class InterlinearConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'updated_at', 'updated_by')
    readonly_fields = ('updated_at',)
    fields = ('mapping', 'updated_by', 'updated_at')
    search_fields = ('updated_by',)
    ordering = ('-updated_at',)
