jQuery(function($){
    let queueItems = [];
    let masterTimer = null;

    // Prevent header controls from toggling the accordion (handles click + mousedown)
    $(document).on('mousedown click', '.rbt-accordion-header input, .rbt-accordion-header button, .rbt-accordion-header a', function(e){
        e.stopPropagation();
    });

    // Accordion toggle (delegated so it works even if items are re-rendered)
    $(document).on('click', '.rbt-accordion-header', function(e){
        // Do not toggle if clicking on interactive elements
        if ($(e.target).is('input, button, a') || $(e.target).closest('input, button, a').length) {
            return;
        }
        $(this).closest('.rbt-accordion-item').toggleClass('active');
    });

    $('#rbt-save-settings').on('click', function(){
        const menuJson = $('#rbt-menu-label-translations').val();
        if (menuJson && menuJson.trim()) {
            try {
                JSON.parse(menuJson);
            } catch (e) {
                $('#rbt-settings-status').text('Invalid JSON: ' + (e && e.message ? e.message : 'Syntax error'));
                return;
            }
        }

        const data = {
            action: 'rbt_save_settings',
            nonce: rbtTranslator.nonce,
            gemini_keys: $('#rbt-gemini-keys').val(),
            batch_size: $('#rbt-batch-size').val(),
            auto_publish_on_source_publish: $('#rbt-auto-publish').is(':checked') ? '1' : '0',
            menu_label_translations: menuJson,
            gemini_model: $('#rbt-gemini-model').val(),
            model_provider: $('#rbt-model-provider').val(),
            openai_api_key: $('#rbt-openai-key').val(),
            openai_model: $('#rbt-openai-model').val(),
            openai_batch_mode: $('#rbt-openai-batch-mode').is(':checked') ? '1' : '0',
            openai_batch_size: $('#rbt-openai-batch-size').val(),
            openai_batch_window: $('#rbt-openai-batch-window').val(),
            gemini_timeout: $('#rbt-gemini-timeout').val()
        };
        $('#rbt-settings-status').text('Saving...');
        $.post(rbtTranslator.ajaxUrl, data).done(function(res){
            $('#rbt-settings-status').text(res?.data?.message || 'Saved');
            // Update displayed current model from server response
            var modelVal = res?.data?.gemini_model || $('#rbt-gemini-model').val() || '';
            $('#rbt-current-model').text(modelVal);
            // also set the input to the sanitized server value
            $('#rbt-gemini-model').val(modelVal);
            if (res?.data?.openai_model) {
                $('#rbt-openai-model').val(res.data.openai_model);
                $('#rbt-openai-current-model').text(res.data.openai_model);
            }
            $('#rbt-test-result').text('');
        }).fail(function(xhr){
            let msg = 'Failed';
            try {
                msg = xhr?.responseJSON?.data?.message || xhr?.responseText || 'Failed';
            } catch (e) {
                msg = 'Failed';
            }
            $('#rbt-settings-status').text(msg);
        });
    });

    function toggleProviderSettings(){
        const provider = $('#rbt-model-provider').val();
        if (provider === 'openai') {
            $('#rbt-openai-settings').show();
            $('#rbt-gemini-settings').hide();
        } else {
            $('#rbt-openai-settings').hide();
            $('#rbt-gemini-settings').show();
        }
    }

    $('#rbt-model-provider').on('change', function(){
        toggleProviderSettings();
    });

    toggleProviderSettings();

    function syncGeminiModelSelect(){
        const selected = $('#rbt-gemini-model-select').val();
        if (selected && selected !== 'custom') {
            $('#rbt-gemini-model').val(selected).prop('disabled', true);
        } else {
            $('#rbt-gemini-model').prop('disabled', false);
        }
    }

    $('#rbt-gemini-model-select').on('change', function(){
        syncGeminiModelSelect();
    });

    // Initialize select state based on current value
    (function(){
        const current = $('#rbt-gemini-model').val();
        if ($('#rbt-gemini-model-select option[value="' + current + '"]').length) {
            $('#rbt-gemini-model-select').val(current);
        } else {
            $('#rbt-gemini-model-select').val('custom');
        }
        syncGeminiModelSelect();
    })();

    // Server computes freshness; JS just reads it.
    function computeFreshness(info){
        if (info.freshness === 'up_to_date') {
            return { label: 'up to date', cls: 'status-up-to-date' };
        }
        if (info.freshness === 'out_of_date') {
            return { label: 'out of date', cls: 'status-out-of-date' };
        }
        if (info.status !== 'completed' || !info.translated_post_id) {
            return { label: 'not complete', cls: 'status-not-complete' };
        }
        return { label: 'out of date', cls: 'status-out-of-date' };
    }

    function updateHeaderStats(postId, perLangStatus){
        const $item = $('.rbt-accordion-item[data-post-id="'+postId+'"]');
        const total = $item.find('.rbt-language-card').length || 0;
        const counts = { up:0, out:0, completed:0, not:0, queued:0, processing:0, failed:0, published:0, draft:0 };

        Object.keys(perLangStatus || {}).forEach(function(lang){
            const info = perLangStatus[lang];
            if (info.status === 'queued') counts.queued++;
            else if (info.status === 'processing') counts.processing++;
            else if (info.status === 'failed') counts.failed++;
            else if (info.status === 'completed' && info.translated_post_id) {
                counts.completed++;
                // Count published vs draft using translated_post_status from server
                if (info.translated_post_status === 'publish') counts.published++; else counts.draft++;
                const fresh = computeFreshness(info);
                if (fresh.label === 'up to date') counts.up++; else counts.out++;
            }
        });

        counts.not = Math.max(0, total - (counts.queued + counts.processing + counts.failed + counts.completed));

        // Determine main status badge (logic mirrors PHP)
        let label = 'Up to date';
        let cls = 'rbt-badge-up';
        
        if (counts.failed > 0) {
            label = 'Errors (' + counts.failed + ')';
            cls = 'rbt-badge-failed';
        } else if (counts.processing > 0 || counts.queued > 0) {
            label = 'Processing...';
            cls = 'rbt-badge-processing';
        } else if (counts.not > 0) {
            label = 'Incomplete (' + (total - counts.not) + '/' + total + ')';
            cls = 'rbt-badge-not';
        } else if (counts.out > 0) {
            label = 'Updates needed (' + counts.out + ')';
            cls = 'rbt-badge-out';
        }

        // Build tooltip
        const parts = [];
        if (counts.up) parts.push(counts.up + ' up-to-date');
        if (counts.out) parts.push(counts.out + ' out-of-date');
        if (counts.not) parts.push(counts.not + ' missing');
        if (counts.queued) parts.push(counts.queued + ' queued');
        if (counts.processing) parts.push(counts.processing + ' processing');
        if (counts.failed) parts.push(counts.failed + ' failed');
        const tooltip = parts.join(', ');

        const $hdr = $item.find('.rbt-header-stats');
        if (!$hdr.length) return;
        
        // Update main badge
        const $badge = $hdr.find('.rbt-badge').first();
        if ($badge.length) {
            $badge.text(label).attr('title', tooltip)
                  .removeClass('rbt-badge-up rbt-badge-out rbt-badge-completed rbt-badge-not rbt-badge-queued rbt-badge-processing rbt-badge-failed')
                  .addClass(cls);
        }
    }

    function updateLanguageCardStatus(postId, lang, info){
        const $item = $('.rbt-accordion-item[data-post-id="'+postId+'"]');
        const $card = $item.find('.rbt-language-card[data-lang="'+lang+'"]');
        if (!$card.length) return;
        const freshness = computeFreshness(info);
        $card.find('.rbt-lang-status').text(freshness.label);
        $card.attr('data-freshness', freshness.label);
        if (info.last_translated) {
            $card.find('.rbt-lang-date').text(info.last_translated);
        }
        const $btn = $card.find('.rbt-retranslate');
        // update status link (make clickable when translation exists)
        const $statusLink = $card.find('.rbt-lang-status');
        if (info.translated_post_id && info.translated_permalink) {
            $statusLink.attr('href', info.translated_permalink).attr('data-permalink', info.translated_permalink).removeAttr('aria-disabled').addClass('is-link');
        } else {
            $statusLink.attr('href', '#').attr('data-permalink', '').attr('aria-disabled', 'true').removeClass('is-link');
        }
        $card.removeClass('status-queued status-processing status-completed status-failed status-up-to-date status-out-of-date status-not-complete status-not-translated status-unknown');
        if (info.status === 'completed'){
            $btn.text('Retranslate').prop('disabled', false);
            $card.addClass('status-completed');
        } else if (info.status === 'processing'){
            $btn.text('Processing...').prop('disabled', true);
            $card.addClass('status-processing');
        } else if (info.status === 'queued'){
            $btn.text('Queued').prop('disabled', true);
            $card.addClass('status-queued');
        } else if (info.status === 'failed'){
            $btn.text('Failed — Retry').prop('disabled', false);
            $card.addClass('status-failed');
        } else {
            $btn.text('Translate / Retranslate').prop('disabled', false);
        }
        $card.addClass(freshness.cls);
    }

    // ── Unified Refresh System ──────────────────────────────────────
    // One master loop keeps everything in sync: queue summary, queue items,
    // and ALL language card statuses. No separate timers or timeouts.

    function getVisiblePostIds(){
        const ids = [];
        $('.rbt-accordion-item').each(function(){
            const pid = $(this).data('post-id');
            if (pid) ids.push(String(pid));
        });
        return ids;
    }

    function refreshAllCards(){
        const postIds = getVisiblePostIds();
        if (!postIds.length) return;
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_get_statuses',
            nonce: rbtTranslator.nonce,
            post_ids: postIds
        }).done(function(res){
            if (!res.success) return;
            const statuses = res.data.statuses || {};
            postIds.forEach(function(pid){
                const p = statuses[pid] || {};
                Object.keys(p).forEach(function(lang){
                    updateLanguageCardStatus(pid, lang, p[lang]);
                });
                updateHeaderStats(pid, p);
            });
        });
    }

    function masterRefresh(){
        fetchQueueSummary();
        if ($('#rbt-queue-items').is(':visible')) {
            refreshQueueItems();
        }
        refreshAllCards();
    }

    function startMasterRefresh(){
        if (masterTimer) return;
        masterTimer = setInterval(masterRefresh, 5000);
    }

    $('#rbt-queue-selected').on('click', function(){
        const postIds = $('.rbt-select-post:checked').map(function(){ return $(this).val(); }).get();
        const lang = $('#rbt-language-select').val();
        if (!postIds.length) {
            $('#rbt-queue-status').text('Select at least one item');
            return;
        }
        $('#rbt-queue-status').text('Queueing...');
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_queue_translations',
            nonce: rbtTranslator.nonce,
            post_ids: postIds,
            lang: lang
        }).done(function(res){
            $('#rbt-queue-status').text(res?.data?.message || 'Queued');
            // set immediate UI state and start polling
            postIds.forEach(function(pid){
                const $card = $('.rbt-accordion-item[data-post-id="'+pid+'"] .rbt-language-card[data-lang="'+lang+'"]');
                $card.find('.rbt-lang-status').text('queued').attr('href','#').attr('data-permalink','').attr('aria-disabled','true').removeClass('is-link');
                $card.find('.rbt-retranslate').text('Queued').prop('disabled', true);
            });
            masterRefresh();
        }).fail(function(){
            $('#rbt-queue-status').text('Failed');
        });
    });

    $('.rbt-retranslate').on('click', function(){
        const postId = $(this).closest('.rbt-accordion-item').data('post-id');
        const lang = $(this).data('lang');
        const btn = $(this);
        btn.text('Queueing...');
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_retranslate',
            nonce: rbtTranslator.nonce,
            post_id: postId,
            lang: lang
        }).done(function(){
            btn.text('Queued');
            masterRefresh();
        }).fail(function(){
            btn.text('Failed');
        });
    });

    // Publish all translations for a source
    $(document).on('click', '.rbt-publish-translations', function(e){
        e.preventDefault();
        e.stopPropagation();
        const postId = $(this).data('post-id');
        const btn = $(this);
        if (!postId) return;
        if (!confirm('Publish all existing translations for this source?')) return;
        btn.text('Publishing...').prop('disabled', true);
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_publish_translations',
            nonce: rbtTranslator.nonce,
            post_id: postId
        }).done(function(res){
            if (!res.success) {
                btn.text('Publish').prop('disabled', false);
                alert(res?.data?.message || 'Failed to publish translations');
                return;
            }
            const count = res.data.count || 0;
            btn.text('Published (' + count + ')');
            masterRefresh();
        }).fail(function(){
            btn.text('Publish').prop('disabled', false);
        });
    });

    // DELETE all translations for a source
    $(document).on('click', '.rbt-delete-translations', function(e){
        e.preventDefault();
        e.stopPropagation();
        const postId = $(this).data('post-id');
        const btn = $(this);
        if (!postId) return;
        if (!confirm('WARNING: This will PERMANENTLY DELETE all translated posts/pages for this source.\n\nAre you sure you want to delete them?')) return;
        
        btn.text('Deleting...').prop('disabled', true);
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_delete_translations',
            nonce: rbtTranslator.nonce,
            post_id: postId
        }).done(function(res){
            if (!res.success) {
                btn.text('Delete Translations').prop('disabled', false);
                alert(res?.data?.message || 'Failed to delete translations');
                return;
            }
            btn.text('Deleted');
            masterRefresh();
            
            // Re-enable button after short delay so user sees "Deleted"
            setTimeout(function(){
                btn.text('Delete Translations').prop('disabled', false);
            }, 2000);
        }).fail(function(){
            btn.text('Delete Translations').prop('disabled', false);
            alert('Request failed');
        });
    });

    // Publish ALL draft translations globally
    $('#rbt-publish-all-drafts').on('click', function(e){
        e.preventDefault();
        const btn = $(this);
        if (!confirm('Publish ALL completed translations that are currently in draft status?')) return;
        btn.text('Publishing all...').prop('disabled', true);
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_publish_all_drafts',
            nonce: rbtTranslator.nonce
        }).done(function(res){
            if (!res.success) {
                btn.text('Publish All Drafts').prop('disabled', false);
                alert(res?.data?.message || 'Failed');
                return;
            }
            btn.text('Done (' + (res.data.count || 0) + ' published)');
            masterRefresh();
            setTimeout(function(){ btn.text('Publish All Drafts').prop('disabled', false); }, 3000);
        }).fail(function(){
            btn.text('Publish All Drafts').prop('disabled', false);
            alert('Request failed');
        });
    });

    // Repair video/media blocks in translations
    $('#rbt-repair-video').on('click', function(e){
        e.preventDefault();
        const btn = $(this);
        if (!confirm('Scan all translations and restore video/audio blocks that were stripped during translation?')) return;
        btn.text('Repairing...').prop('disabled', true);
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_repair_video',
            nonce: rbtTranslator.nonce
        }).done(function(res){
            if (!res.success) {
                btn.text('Repair Video/Media').prop('disabled', false);
                alert(res?.data?.message || 'Failed');
                return;
            }
            const msg = (res.data.count || 0) + ' repaired';
            btn.text('Done (' + msg + ')');
            if (res.data.details && res.data.details.length) {
                console.log('Repaired translations:', res.data.details);
            }
            masterRefresh();
            setTimeout(function(){ btn.text('Repair Video/Media').prop('disabled', false); }, 3000);
        }).fail(function(){
            btn.text('Repair Video/Media').prop('disabled', false);
            alert('Request failed');
        });
    });

    // Queue summary polling and queue view
    function fetchQueueSummary(){
        $.post(rbtTranslator.ajaxUrl, {
            action: 'rbt_get_queue_summary',
            nonce: rbtTranslator.nonce
        }).done(function(res){
            if (!res.success) return;
            const s = res.data.summary || {};
            const queued = s.queued || 0;
            const processing = s.processing || 0;
            const failed = s.failed || 0;
            $('#rbt-queue-count').text(`${queued} queued · ${processing} processing · ${failed} failed`);
            $('#rbt-last-run').text(res.data.last_run || 'never');
            if (res.data.next_run) {
                $('#rbt-last-run').append(' · Next: ' + res.data.next_run);
            }
            // Auto-open queue panel if there are active items
            if ((queued > 0 || processing > 0) && !$('#rbt-queue-items').is(':visible')) {
                $('#rbt-queue-items').show();
                refreshQueueItems(true);
            }
        });
    }

    // Kick off unified refresh: queue + cards every 5s, forever.
    masterRefresh();
    startMasterRefresh();

    function refreshQueueItems(showLoading){
        if (showLoading) {
            $('#rbt-queue-table-wrap').html('<div style="padding:8px;">Loading…</div>');
        }
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_get_queue_items', nonce: rbtTranslator.nonce }).done(function(res){
            if (!res.success) return;
            renderQueueItems(res.data.items || []);
        });
    }

    $('#rbt-view-queue').on('click', function(){
        const wrap = $('#rbt-queue-items');
        if (wrap.is(':visible')){
            wrap.hide();
            return;
        }
        refreshQueueItems(true);
        wrap.show();
    });

    $('#rbt-queue-refresh').on('click', function(){
        refreshQueueItems(true);
    });

    $('#rbt-queue-search, #rbt-queue-status-filter').on('input change', function(){
        renderQueueItems();
    });

    $(document).on('click', '#rbt-view-log', function(){
        console.log('View Log clicked');
        const wrap = $('#rbt-log-viewer');
        if (wrap.is(':visible')){
            wrap.hide();
            return;
        }
        console.log('Fetching log...');
        // fetch log
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_get_log', nonce: rbtTranslator.nonce }).done(function(res){
            console.log('Log response:', res);
            if (!res.success) return;
            const log = res.data.log || [];
            renderLog(log);
            $('#rbt-log-viewer').show();
        }).fail(function(xhr, status, error){
            console.error('Log fetch failed:', status, error);
        });
    });
    // Test model button
    $('#rbt-test-model').on('click', function(e){
        e.preventDefault();
        const provider = $('#rbt-model-provider').val();
        const model = provider === 'openai' ? ($('#rbt-openai-model').val() || '') : ($('#rbt-gemini-model').val() || '');
        if (!model) {
            $('#rbt-test-result').text('Enter a model name first');
            return;
        }
        $('#rbt-test-result').text('Testing...');
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_test_model', nonce: rbtTranslator.nonce, model: model, provider: provider }).done(function(res){
            if (res.success) {
                $('#rbt-test-result').text('OK — model accepted');
            } else {
                $('#rbt-test-result').text('Failed: ' + (res?.data?.message || 'Unknown'));
            }
        }).fail(function(xhr){
            let msg = 'Failed';
            try { msg = xhr?.responseJSON?.data?.message || xhr?.responseText || 'Failed'; } catch(e) { msg = 'Failed'; }
            $('#rbt-test-result').text('Error: ' + msg);
        });
    });

    $('#rbt-test-model-openai').on('click', function(e){
        e.preventDefault();
        const model = $('#rbt-openai-model').val() || '';
        if (!model) {
            $('#rbt-test-result').text('Select an OpenAI model first');
            return;
        }
        $('#rbt-test-result').text('Testing...');
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_test_model', nonce: rbtTranslator.nonce, model: model, provider: 'openai' }).done(function(res){
            if (res.success) {
                $('#rbt-test-result').text('OK — model accepted');
            } else {
                $('#rbt-test-result').text('Failed: ' + (res?.data?.message || 'Unknown'));
            }
        }).fail(function(xhr){
            let msg = 'Failed';
            try { msg = xhr?.responseJSON?.data?.message || xhr?.responseText || 'Failed'; } catch(e) { msg = 'Failed'; }
            $('#rbt-test-result').text('Error: ' + msg);
        });
    });

    // Menu Labels page save handler
    $(document).on('click', '#rbt-save-menu-labels', function(){
        const $btn = $(this);
        const txt = $('#rbt-menu-labels-json').val() || '';
        const ftxt = $('#rbt-footer-menu-labels-json').val() || '';
        try {
            if (txt && txt.trim()) JSON.parse(txt);
            if (ftxt && ftxt.trim()) JSON.parse(ftxt);
        } catch (e) {
            $('#rbt-menu-label-status').text('Invalid JSON: ' + (e && e.message ? e.message : 'Syntax error'));
            return;
        }
        $btn.prop('disabled', true).text('Saving...');
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_save_menu_labels', nonce: rbtTranslator.nonce, menu_labels: txt, footer_menu_labels: ftxt }).done(function(res){
            if (!res.success) {
                $('#rbt-menu-label-status').text(res?.data?.message || 'Failed');
                $('#rbt-footer-menu-label-status').text(res?.data?.message || 'Failed');
                $btn.prop('disabled', false).text('Save');
                return;
            }
            $('#rbt-menu-label-status').text('Saved');
            $('#rbt-footer-menu-label-status').text('Saved');
            $btn.prop('disabled', false).text('Save');
        }).fail(function(){
            $('#rbt-menu-label-status').text('Failed');
            $('#rbt-footer-menu-label-status').text('Failed');
            $btn.prop('disabled', false).text('Save');
        });
    });
    $(document).on('click', '#rbt-clear-log', function(){
        if (!confirm('Clear all log entries?')) return;
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_clear_log', nonce: rbtTranslator.nonce }).done(function(res){
            $('#rbt-log-wrap').html('<em>Log cleared</em>');
        });
    });

    // Clear completed queue items (orphan rows only)
    $(document).on('click', '#rbt-clear-completed', function(){
        if (!confirm('Delete completed rows that have no linked translation?')) return;
        const $btn = $(this).prop('disabled', true).text('Clearing...');
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_clear_completed', nonce: rbtTranslator.nonce }).done(function(res){
            if (!res.success) {
                alert(res?.data?.message || 'Failed');
                $btn.prop('disabled', false).text('Clear completed (orphans only)');
                return;
            }
            const n = res.data.count || 0;
            $('#rbt-queue-count').text(n + ' cleared');
            fetchQueueSummary();
            if ($('#rbt-queue-items').is(':visible')) {
                refreshQueueItems();
            }
            $btn.text('Clear completed (orphans only)').prop('disabled', false);
        }).fail(function(){
            alert('Failed to clear completed items');
            $btn.prop('disabled', false).text('Clear completed (orphans only)');
        });
    });

    function renderLog(log){
        if (!log || !log.length) {
            $('#rbt-log-wrap').html('<em>No log entries</em>');
            return;
        }
        let html = '';
        log.forEach(function(entry){
            const ctx = entry.context && Object.keys(entry.context).length ? ' | ' + JSON.stringify(entry.context) : '';
            html += '[' + entry.time + '] ' + entry.message + ctx + '\n';
        });
        $('#rbt-log-wrap').html(html);
    }

    function renderQueueItems(items){
        if (items) {
            queueItems = items;
        }

        const term = ($('#rbt-queue-search').val() || '').toLowerCase();
        const statusFilter = $('#rbt-queue-status-filter').val() || 'all';

        const filtered = queueItems.filter(function(it){
            const matchesStatus = statusFilter === 'all' || (it.status === statusFilter);
            const matchesTerm = !term || (it.title && it.title.toLowerCase().includes(term)) || (it.lang && it.lang.toLowerCase().includes(term));
            return matchesStatus && matchesTerm;
        });

        const order = ['processing','queued','failed','completed','cancelled','pending','unknown'];
        const grouped = {};
        filtered.forEach(function(it){
            const key = it.status || 'unknown';
            if (!grouped[key]) grouped[key] = [];
            grouped[key].push(it);
        });

        let html = '<div class="rbt-queue-groups" style="display:flex; flex-wrap:wrap; gap:12px;">';
        order.forEach(function(key){
            if (!grouped[key] || !grouped[key].length) return;
            const list = grouped[key];
            // Completed items are already pre-limited to 20 by the server query.
            const displayList = list;
            const hiddenCount = 0;
            html += `<div class="rbt-queue-card" style="flex:1 1 320px; border:1px solid #ddd; border-radius:4px; padding:10px; background:#fff;">`;
            html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;"><strong style="text-transform:capitalize;">${key}</strong><span class="rbt-badge">${list.length}</span></div>`;
            html += '<ul style="list-style:none; margin:0; padding:0; max-height:260px; overflow-y:auto;">';
            displayList.forEach(function(it){
                const nextRetry = it.next_retry ? ` · next: ${it.next_retry}` : '';
                html += `<li style="border-top:1px solid #eee; padding:6px 0;">`;
                html += `<div style="font-weight:600;">${it.title || '(untitled)'} <span style="color:#555;">[${it.lang}]</span></div>`;
                const timeLabel = (it.status === 'completed' && it.updated_at)
                    ? `translated ${it.updated_at}`
                    : `created ${it.created_at}`;
                html += `<div style="font-size:12px; color:#666;">id ${it.id} · attempts ${it.attempts}${nextRetry} · ${timeLabel}</div>`;
                html += `<div style="margin-top:4px; display:flex; gap:6px; flex-wrap:wrap;">`;
                if (it.status === 'queued' || it.status === 'processing') {
                    html += `<button class="button rbt-cancel" data-id="${it.id}">Cancel</button>`;
                }
                if (it.status === 'failed' || it.status === 'cancelled') {
                    html += `<button class="button rbt-retry" data-id="${it.id}">Retry</button>`;
                }
                html += `</div>`;
                html += `</li>`;
            });
            if (hiddenCount > 0) {
                html += `<li style="border-top:1px solid #eee; padding:6px 0; color:#888; font-size:12px;">… and ${hiddenCount} more (oldest hidden)</li>`;
            }
            html += '</ul></div>';
        });

        if (filtered.length === 0) {
            html += '<div style="padding:8px; color:#555;">No items match the filters.</div>';
        }

        html += '</div>';
        $('#rbt-queue-table-wrap').html(html);

        $('.rbt-cancel').on('click', function(){
            const id = $(this).data('id');
            $.post(rbtTranslator.ajaxUrl, { action: 'rbt_cancel_translation', nonce: rbtTranslator.nonce, id: id }).done(function(){
                fetchQueueSummary();
                refreshQueueItems();
            });
        });
        $('.rbt-retry').on('click', function(){
            const id = $(this).data('id');
            $.post(rbtTranslator.ajaxUrl, { action: 'rbt_retry_translation', nonce: rbtTranslator.nonce, id: id }).done(function(){
                fetchQueueSummary();
                refreshQueueItems();
            });
        });
    }

    $('#rbt-run-now').on('click', function(){
        $('#rbt-run-now').text('Running...');
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_run_now', nonce: rbtTranslator.nonce }).done(function(res){
            $('#rbt-run-now').text('Run Now');
            fetchQueueSummary();
            if (res.success && res.data.last_run) {
                $('#rbt-last-run').text(res.data.last_run);
            }
        }).fail(function(){
            $('#rbt-run-now').text('Run Now');
        });
    });

    $('#rbt-requeue-outdated').on('click', function(){
        const $btn = $(this);
        $btn.text('Re-queuing...').prop('disabled', true);
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_requeue_out_of_date', nonce: rbtTranslator.nonce }).done(function(res){
            $btn.text('Re-queue Out-of-date').prop('disabled', false);
            if (res.success && res.data.message) {
                $('#rbt-queue-count').text(res.data.message);
            }
            fetchQueueSummary();
        }).fail(function(){
            $btn.text('Re-queue Out-of-date').prop('disabled', false);
        });
    });

    $('#rbt-fix-internal-links').on('click', function(){
        const $btn = $(this);
        if (!confirm('Scan all completed translations and fix internal links that point to English slugs?\n\nThis will update translated posts in-place. It may take a moment.')) return;
        $btn.text('Fixing...').prop('disabled', true);
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_fix_internal_links', nonce: rbtTranslator.nonce })
            .done(function(res){
                const count = res?.data?.count ?? 0;
                const msg = res?.data?.message || `Done (${count} post${count !== 1 ? 's' : ''} updated)`;
                $btn.text(msg).prop('disabled', false);
                alert(msg); // Show alert for better visibility
                setTimeout(() => { $btn.text('Fix Internal Links').prop('disabled', false); }, 3000);
            }).fail(function(xhr, status, error){
                $btn.text('Failed').prop('disabled', false);
                alert(`Error: ${error || status || 'Unknown error'}`);
                setTimeout(() => { $btn.text('Fix Internal Links').prop('disabled', false); }, 3000);
            });
    });

    // Source search/add/remove
    function renderSourceResults(items){
        if (!items.length) {
            $('#rbt-source-results').html('<div class="rbt-source-empty">No results</div>');
            return;
        }
        let html = '<ul class="rbt-source-list">';
        items.forEach(function(it){
            const disabled = it.is_root ? 'disabled' : '';
            const label = it.is_root ? 'Added' : 'Add';
            html += `<li><strong>${it.title}</strong> <span class="rbt-source-meta">${it.type} · ${it.status}</span> ` +
                    `<button class="button rbt-add-source" data-id="${it.id}" ${disabled}>${label}</button></li>`;
        });
        html += '</ul>';
        $('#rbt-source-results').html(html);
        $('.rbt-add-source').on('click', function(){
            const id = $(this).data('id');
            $.post(rbtTranslator.ajaxUrl, { action: 'rbt_add_source_root', nonce: rbtTranslator.nonce, post_id: id }).done(function(){
                location.reload();
            });
        });
    }

    // Prevent clicking status when permalink missing
    $(document).on('click', '.rbt-lang-status', function(e){
        const href = $(this).attr('data-permalink') || '';
        if (!href) {
            e.preventDefault();
            return false;
        }
        // otherwise allow opening in new tab (anchor has target=_blank)
    });

    $('#rbt-source-search-btn').on('click', function(){
        const q = $('#rbt-source-search').val();
        if (!q) return;
        $('#rbt-source-results').html('<div class="rbt-source-empty">Searching...</div>');
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_search_sources', nonce: rbtTranslator.nonce, q: q }).done(function(res){
            if (!res.success) return;
            renderSourceResults(res.data.items || []);
        });
    });

    $('#rbt-source-search').on('keydown', function(e){
        if (e.key === 'Enter') {
            e.preventDefault();
            $('#rbt-source-search-btn').click();
        }
    });

    $('.rbt-remove-source').on('click', function(e){
        e.preventDefault();
        e.stopPropagation();
        const id = $(this).data('post-id');
        if (!id) return;
        if (!confirm('Remove this source from the list?')) return;
        $.post(rbtTranslator.ajaxUrl, { action: 'rbt_remove_source_root', nonce: rbtTranslator.nonce, post_id: id }).done(function(){
            location.reload();
        });
    });
});
