"""
Statistics and analytics views for translation updates and usage tracking.
"""

import re
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db.models import Count
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncHour
from dateutil.relativedelta import relativedelta

from search.models import TranslationUpdates, GenesisFootnotes
from search.db_utils import execute_query
from translate.translator import convert_book_name


@csrf_exempt
def update_count(request):
    """Get count of translation updates for today."""
    if request.method == 'GET':
        today = datetime.now()

        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)

        update_count = TranslationUpdates.objects.filter(
            date__range=[start_date, end_date]
        ).count()

        response = JsonResponse({'updateCount': update_count})
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"

        return response


def update_statistics_view(request):
    """Render the statistics dashboard page."""
    return render(request, 'statistics.html')


@csrf_exempt
@require_http_methods(["GET"])
def update_statistics_api(request):
    """
    API endpoint for fetching update statistics.
    
    Query params:
    - days: Number of days to look back (default: 30, supports 'all')
    
    Returns comprehensive statistics including:
    - Daily/weekly/monthly aggregations
    - Top 100 most updated references
    - Hourly and weekday patterns
    - Bible completion percentage
    - OT and NT footnote counts
    """
    try:
        days_param = request.GET.get('days', '30')
        end_date = datetime.now()

        # Handle "all" case for days parameter
        if days_param == 'all':
            start_date = datetime(2024, 1, 1)
            days_back = (end_date - start_date).days
        else:
            try:
                days_back = max(0, int(days_param))
                start_date = end_date - timedelta(days=days_back)
            except (ValueError, TypeError):
                days_back = 30
                start_date = end_date - timedelta(days=30)

        # Base queryset filtered by date range
        base_queryset = TranslationUpdates.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )

        # 1. Daily updates
        daily_updates = list(
            base_queryset
            .annotate(day=TruncDate('date'))
            .values('day')
            .annotate(count=Count('date'))
            .order_by('day')
        )

        daily_data = {}
        for item in daily_updates:
            daily_data[item['day'].strftime('%Y-%m-%d')] = item['count']

        complete_daily_data = []
        current_date = start_date.date()
        while current_date <= end_date.date():
            date_str = current_date.strftime('%Y-%m-%d')
            complete_daily_data.append({
                'date': date_str,
                'count': daily_data.get(date_str, 0)
            })
            current_date += timedelta(days=1)

        # 2. Top 100 references
        top_references = list(
            base_queryset
            .exclude(reference__isnull=True)
            .exclude(reference__exact='')
            .exclude(reference='[]')
            .values('reference')
            .annotate(count=Count('date'))
            .order_by('-count')[:100]
        )

        # Generate links for each reference (Format A only)
        base_url = "https://rbtproject.up.railway.app"
        for item in top_references:
            reference = item['reference']
            try:
                parts = reference.strip().split()
                if len(parts) == 2:
                    book = parts[0]
                    chapter, verse = parts[1].split(':')
                    query_params = urlencode({
                        'book': book,
                        'chapter': chapter,
                        'verse': verse
                    })
                    item['link'] = f"{base_url}?{query_params}"
                else:
                    item['link'] = None
            except Exception:
                item['link'] = None

        # 3. Weekly aggregation
        weekly_updates = list(
            base_queryset
            .annotate(week=TruncWeek('date'))
            .values('week')
            .annotate(count=Count('date'))
            .order_by('week')
        )

        # 4. Monthly aggregation
        monthly_updates = list(
            base_queryset
            .annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(count=Count('date'))
            .order_by('month')
        )

        # 5. Hourly pattern
        hourly_updates = (
            base_queryset
            .annotate(hour=TruncHour('date'))
            .values('hour')
            .annotate(count=Count('date'))
            .order_by('hour')
        )

        hourly_pattern = []
        hour_counts = defaultdict(int)
        for item in hourly_updates:
            hour_counts[item['hour'].hour] += item['count']

        for hour in range(24):
            hourly_pattern.append({'hour': hour, 'count': hour_counts.get(hour, 0)})

        # 6. Weekday pattern (last 4 weeks)
        four_weeks_ago = end_date - timedelta(weeks=4)
        weekday_stats = defaultdict(int)
        weekday_data = TranslationUpdates.objects.filter(
            date__gte=four_weeks_ago,
            date__lte=end_date
        ).values('date')

        for item in weekday_data:
            weekday = item['date'].strftime('%A')
            weekday_stats[weekday] += 1

        weekday_pattern = [
            {'day': day, 'count': weekday_stats[day]}
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        ]

        # 7. Summary statistics
        total_updates = base_queryset.count()
        unique_references = base_queryset.values('reference').distinct().count()
        avg_daily = total_updates / max(days_back, 1)

        TOTAL_BIBLE_VERSES = 31102
        bible_completion_percentage = round((unique_references / TOTAL_BIBLE_VERSES) * 100, 2)

        # 8. Most active day
        most_active_day = max(complete_daily_data, key=lambda x: x['count']) if complete_daily_data else None

        # 9. Count unique OT references (pattern: e.g., '2-16-86')
        ot_footnote_pattern = re.compile(r'^\d+-\d+-\d+$')
        ot_footnote_references = set()
        for ref in base_queryset.exclude(reference__isnull=True).exclude(reference__exact='').values_list('reference', flat=True):
            if ot_footnote_pattern.match(ref.strip()):
                ot_footnote_references.add(ref.strip())
        ot_footnote_count = len(ot_footnote_references)
        # add the Genesis footnote count
        ot_footnote_count = ot_footnote_count + GenesisFootnotes.objects.filter(footnote_id__isnull=False).count()

        # Get all footnote tables
        footnote_tables = execute_query("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'new_testament' 
            AND table_name LIKE '%_footnotes'
        """, fetch='all')

        nt_footnote_count = 0

        for table_row in footnote_tables:
            table_name = table_row[0]
            count_result = execute_query(
                f"SELECT COUNT(*) FROM new_testament.{table_name} WHERE footnote_id IS NOT NULL",
                fetch='one'
            )
            if count_result:
                nt_footnote_count += count_result[0]

        return JsonResponse({
            'summary': {
                'total_updates': total_updates,
                'unique_references': unique_references,
                'ot_footnote_count': ot_footnote_count,
                'nt_footnote_count': nt_footnote_count,
                'average_daily': round(avg_daily, 0),
                'date_range': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d'),
                    'days': 'all' if days_param == 'all' else days_back
                },
                'most_active_day': most_active_day
            },
            'daily_updates': complete_daily_data,
            'weekly_updates': [
                {
                    'week': item['week'].strftime('%Y-%m-%d'),
                    'count': item['count']
                } for item in weekly_updates
            ],
            'monthly_updates': [
                {
                    'month': item['month'].strftime('%Y-%m'),
                    'count': item['count']
                } for item in monthly_updates
            ],
            'top_references': top_references,
            'hourly_pattern': hourly_pattern,
            'weekday_pattern': weekday_pattern,
            'bible_completion': {
                'unique_verses': unique_references,
                'total_verses': TOTAL_BIBLE_VERSES,
                'percentage_complete': bible_completion_percentage
            }
        })

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def visitor_locations_api(request):
    """
    API endpoint for fetching visitor locations for the heatmap.
    """
    try:
        from search.models import VisitorLocation
        
        # Get locations from the last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        locations = VisitorLocation.objects.filter(
            timestamp__gte=thirty_days_ago,
            is_bot=False,
            latitude__isnull=False,
            longitude__isnull=False
        ).values('latitude', 'longitude').annotate(count=Count('id'))
        
        data = [
            [loc['latitude'], loc['longitude'], loc['count']]
            for loc in locations
        ]
        
        return JsonResponse({'locations': data})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
