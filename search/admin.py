from django.contrib import admin, messages
from django.utils.html import format_html
from .models import InterlinearConfig, InterlinearApplyLog
from . import utils


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


@admin.register(InterlinearConfig)
class InterlinearConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'updated_at', 'updated_by')
    readonly_fields = ('updated_at',)
    fields = ('mapping', 'updated_by', 'updated_at')
    search_fields = ('updated_by',)
    ordering = ('-updated_at',)
    actions = [admin_dry_run_apply, admin_commit_apply]


@admin.register(InterlinearApplyLog)
class InterlinearApplyLogAdmin(admin.ModelAdmin):
    list_display = ('applied_at', 'user', 'committed', 'applied_count', 'total_candidates')
    readonly_fields = ('applied_at', 'user', 'committed', 'applied_count', 'total_candidates', 'sample', 'backup_file')
    search_fields = ('user',)
    ordering = ('-applied_at',)
