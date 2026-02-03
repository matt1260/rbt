from django.contrib import admin, messages
from django.core.cache import cache
from django.urls import path, reverse
from django.utils.html import format_html
from django.shortcuts import redirect
from .models import InterlinearConfig, InterlinearApplyLog
from . import utils
from search.views.chapter_views_part1 import INTERLINEAR_CACHE_VERSION


@admin.action(description='Dry-run: show sample interlinear replacements')
def admin_dry_run_apply(modeladmin, request, queryset):
    # use latest config (or selected)
    try:
        mapping = utils.load_mapping_from_db_or_file(None)
    except Exception as exc:
        modeladmin.message_user(request, f'Failed to load mapping: {exc}', level=messages.ERROR)
        return

    result = utils.apply_interlinear(mapping, dry_run=True, limit=20)
    total = result.get('total_candidates')
    samples = result.get('samples', [])

    if not samples:
        modeladmin.message_user(request, f'No replacements to show ({total} candidates).', level=messages.INFO)
        return

    modeladmin.message_user(request, f'Found {total} potential replacements. Showing up to {len(samples)} samples.')
    for s, lem, old, new in samples:
        modeladmin.message_user(request, f"{s} | {lem} : '{old}' -> '{new}'")

    # create a log entry
    InterlinearApplyLog.objects.create(
        user=request.user.username if request.user else None,
        committed=False,
        total_candidates=total,
        applied_count=0,
        sample='\n'.join([f"{s}|{lem}:'{old}'->'{new}'" for s, lem, old, new in samples])
    )


@admin.action(description='Apply mapping to Strong\'s (commit)')
def admin_commit_apply(modeladmin, request, queryset):
    if not request.user.is_superuser:
        modeladmin.message_user(request, 'Only superusers may perform the commit. Please run the management command or ask a superuser.', level=messages.ERROR)
        return

    try:
        mapping = utils.load_mapping_from_db_or_file(None)
    except Exception as exc:
        modeladmin.message_user(request, f'Failed to load mapping: {exc}', level=messages.ERROR)
        return

    # perform commit (will write backup file)
    try:
        result = utils.apply_interlinear(mapping, dry_run=False, limit=20, clear_mapping_on_commit=True, user=request.user.username if request.user else None)
    except Exception as exc:
        modeladmin.message_user(request, f'Failed to apply mapping: {exc}', level=messages.ERROR)
        return

    total = result.get('total_candidates')
    applied = result.get('applied')
    backup_file = result.get('backup_file')

    InterlinearApplyLog.objects.create(
        user=request.user.username if request.user else None,
        committed=True,
        total_candidates=total,
        applied_count=applied,
        sample='\n'.join([f"{s}|{lem}:'{old}'->'{new}'" for s, lem, old, new in result.get('samples', [])]),
        backup_file=backup_file
    )

    modeladmin.message_user(request, f'Applied {applied} replacements. Backup: {backup_file}')


@admin.action(description='Clear cached verse data (Interlinear)')
def admin_clear_cache(modeladmin, request, queryset):
    try:
        cache_pattern = f'*_{INTERLINEAR_CACHE_VERSION}'
        if hasattr(cache, 'delete_pattern'):
            deleted = cache.delete_pattern(cache_pattern)
            modeladmin.message_user(request, f'Cleared {deleted} verse cache keys with pattern {cache_pattern}.')
        else:
            cache.clear()
            modeladmin.message_user(request, 'Cleared entire cache (cache backend has no delete_pattern).')
    except Exception as exc:
        modeladmin.message_user(request, f'Failed to clear cache: {exc}', level=messages.ERROR)


def clear_interlinear_cache(request):
    try:
        cache_pattern = f'*_{INTERLINEAR_CACHE_VERSION}'
        if hasattr(cache, 'delete_pattern'):
            deleted = cache.delete_pattern(cache_pattern)
            messages.info(request, f'Cleared {deleted} verse cache keys with pattern {cache_pattern}.')
        else:
            cache.clear()
            messages.info(request, 'Cleared entire cache (cache backend has no delete_pattern).')
    except Exception as exc:
        messages.error(request, f'Failed to clear cache: {exc}')
@admin.register(InterlinearConfig)
class InterlinearConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'updated_at', 'updated_by')
    readonly_fields = ('updated_at',)
    fields = ('mapping', 'updated_by', 'updated_at')
    search_fields = ('updated_by',)
    ordering = ('-updated_at',)
    change_list_template = 'admin/search/interlinearconfig/change_list.html'
    actions = [admin_dry_run_apply, admin_commit_apply, admin_clear_cache]

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('clear-cache/', self.admin_site.admin_view(self.clear_cache_view), name='search_interlinearconfig_clear_cache'),
        ]
        return custom + urls

    def clear_cache_view(self, request):
        if request.method != 'POST':
            return redirect('admin:search_interlinearconfig_changelist')

        clear_interlinear_cache(request)
        return redirect('admin:search_interlinearconfig_changelist')


@admin.register(InterlinearApplyLog)
class InterlinearApplyLogAdmin(admin.ModelAdmin):
    list_display = ('applied_at', 'user', 'committed', 'applied_count', 'total_candidates')
    readonly_fields = ('applied_at', 'user', 'committed', 'applied_count', 'total_candidates', 'sample', 'backup_file')
    search_fields = ('user',)
    ordering = ('-applied_at',)
