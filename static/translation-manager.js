// Language modal functions
function changeLanguage(langCode) {
    const currentLang = new URLSearchParams(window.location.search).get('lang') || 'en';
    
    if (langCode !== currentLang && langCode !== 'en') {
        if (typeof closeLanguageModal === 'function') {
            closeLanguageModal();
        }
        if (typeof showTranslationLoading === 'function') {
            showTranslationLoading();
        }
    }

    const url = new URL(window.location);
    url.searchParams.set('lang', langCode);
    window.location.href = url.toString();
}

function openLanguageModal() {
    document.getElementById('languageModal').classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeLanguageModal() {
    document.getElementById('languageModal').classList.remove('active');
    document.body.style.overflow = '';
}

// Show/hide translation loading modal
function showTranslationLoading() {
    const modal = document.getElementById('translationLoadingModal');
    if (modal) {
        modal.style.display = 'flex';
        modal.style.opacity = '1';
    }
}

function hideTranslationLoading() {
    const modal = document.getElementById('translationLoadingModal');
    if (modal) {
        modal.style.transition = 'opacity 0.5s ease-out';
        modal.style.opacity = '0';
        setTimeout(function() {
            modal.style.display = 'none';
        }, 500);
    }
}

// Poll for translation job status
function pollJobStatus(jobId, book, chapter, lang, progressText) {
    const pollInterval = 2000; // Poll every 2 seconds
    const maxPolls = 300; // Max 10 minutes
    let pollCount = 0;
    
    const poll = () => {
        pollCount++;
        
        fetch(`/api/translation/status/?job_id=${jobId}`)
            .then(response => response.json())
            .then(data => {
                console.log("Job status:", data);
                
                if (data.status === 'completed') {
                    const verses = data.translated_verses || 0;
                    const footnotes = data.translated_footnotes || 0;
                    if (progressText) {
                        progressText.textContent = `Translated ${verses} verses and ${footnotes} footnotes. Clearing cache...`;
                    }
                    
                    fetch(`/api/translation/clear-cache/?book=${encodeURIComponent(book)}&chapter=${chapter}&lang=${lang}`)
                        .then(() => {
                            if (progressText) progressText.textContent = 'Reloading page...';
                            setTimeout(() => {
                                const url = new URL(window.location.href);
                                url.searchParams.set('_t', Date.now());
                                window.location.href = url.toString();
                            }, 500);
                        });
                        
                } else if (data.status === 'failed') {
                    console.error('Translation job failed:', data.error);
                    if (progressText) {
                        let errorMsg = data.error || 'Unknown error';
                        if (errorMsg.includes('quota') || errorMsg.includes('429')) {
                            progressText.innerHTML = '<span style="color: #d32f2f;">⚠️ Translation quota exhausted</span><br><span style="font-size: 11px; color: #666;">API limits reached. Please try again later.</span>';
                        } else {
                            progressText.innerHTML = '<span style="color: #d32f2f;">⚠️ Translation failed</span><br><span style="font-size: 11px; color: #666;">' + errorMsg + '</span>';
                        }
                    }
                    setTimeout(() => {
                        if (typeof hideTranslationLoading === 'function') hideTranslationLoading();
                    }, 5000);
                    
                } else if (data.status === 'processing' || data.status === 'pending') {
                    const progress = data.progress || 0;
                    const verses = data.translated_verses || 0;
                    const totalVerses = data.total_verses || 0;
                    const footnotes = data.translated_footnotes || 0;
                    const totalFootnotes = data.total_footnotes || 0;
                    
                    if (progressText) {
                        if (data.status === 'pending' && data.queue_position) {
                            let queueMsg = `Position in queue: #${data.queue_position}`;
                            if (data.current_job) {
                                queueMsg += `<br><span style="font-size: 11px; color: #666;">Currently processing: ${data.current_job.book} ${data.current_job.chapter} (${data.current_job.progress}%)</span>`;
                            }
                            progressText.innerHTML = queueMsg;
                        } else if (totalVerses > 0 || totalFootnotes > 0) {
                            progressText.textContent = `Translating ${data.book || ''} ${data.chapter || ''}... ${progress}% (${verses}/${totalVerses} verses, ${footnotes}/${totalFootnotes} footnotes)`;
                        } else {
                            progressText.textContent = data.status === 'pending' ? 'Starting translation...' : 'Processing translation...';
                        }
                    }
                    
                    if (pollCount < maxPolls) {
                        setTimeout(poll, pollInterval);
                    } else {
                        if (progressText) {
                            progressText.innerHTML = '<span style="color: #d32f2f;">⚠️ Translation timeout</span><br><span style="font-size: 11px; color: #666;">Translation is taking too long. It will continue in the background.</span>';
                        }
                        setTimeout(() => {
                            if (typeof hideTranslationLoading === 'function') hideTranslationLoading();
                        }, 5000);
                    }
                    
                } else {
                    console.warn('Unknown job status:', data.status);
                    if (pollCount < maxPolls) {
                        setTimeout(poll, pollInterval);
                    }
                }
            })
            .catch(err => {
                console.error('Poll error:', err);
                if (pollCount < maxPolls) {
                    setTimeout(poll, pollInterval * 2);
                }
            });
    };
    
    poll();
}
