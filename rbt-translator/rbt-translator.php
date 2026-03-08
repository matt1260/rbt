<?php
/**
 * Plugin Name: RBT Translator
 * Description: Manage multi-language translations of posts/pages with Gemini and language-aware redirects.
 * Version: 0.1.0
 * Author: Real Bible Translation Project
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'RBT_TRANSLATOR_VERSION', '0.1.0' );

define( 'RBT_TRANSLATOR_DIR', plugin_dir_path( __FILE__ ) );

define( 'RBT_TRANSLATOR_URL', plugin_dir_url( __FILE__ ) );

class RBT_Translator {
    private static $instance = null;

    public static function instance() {
        if ( self::$instance === null ) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function log( $message, $context = array() ) {
        $log = get_option( 'rbt_translator_log', array() );
        $log[] = array(
            'time' => current_time( 'mysql' ),
            'message' => $message,
            'context' => $context,
        );
        // Keep last 500 entries
        if ( count( $log ) > 500 ) {
            $log = array_slice( $log, -500 );
        }
        update_option( 'rbt_translator_log', $log );
    }

    // --- Key usage tracking helpers ---
    private function get_key_rpm_limit() {
        // Default per-key requests per minute; can be tuned in settings later
        return 20;
    }

    private function key_usage_count( $key ) {
        $k = 'rbt_key_usage_' . md5( $key );
        $count = get_transient( $k );
        return intval( $count );
    }

    private function key_usage_increment( $key ) {
        $k = 'rbt_key_usage_' . md5( $key );
        $count = intval( get_transient( $k ) );
        $count++;
        // Keep counters for slightly over a minute window
        set_transient( $k, $count, 70 );
        return $count;
    }

    private function set_key_next_available( $key, $timestamp ) {
        update_option( 'rbt_key_next_avail_' . md5( $key ), intval( $timestamp ) );
    }

    private function get_key_next_available( $key ) {
        return intval( get_option( 'rbt_key_next_avail_' . md5( $key ), 0 ) );
    }

    private function key_is_available( $key ) {
        $now = current_time( 'timestamp' );
        $next = $this->get_key_next_available( $key );
        if ( $next && $next > $now ) return false;
        $count = $this->key_usage_count( $key );
        $limit = $this->get_key_rpm_limit();
        return $count < $limit;
    }

    private function get_min_key_next_seconds( $keys ) {
        $now = current_time( 'timestamp' );
        $min = PHP_INT_MAX;
        foreach ( $keys as $k ) {
            $next = $this->get_key_next_available( $k );
            if ( $next && $next > $now ) {
                $s = $next - $now;
                if ( $s < $min ) $min = $s;
            }
        }
        return $min === PHP_INT_MAX ? 0 : $min;
    }

    private function __construct() {
        register_activation_hook( __FILE__, array( $this, 'activate' ) );
        add_action( 'admin_menu', array( $this, 'admin_menu' ) );
        add_action( 'admin_enqueue_scripts', array( $this, 'admin_assets' ) );
        add_action( 'wp_enqueue_scripts', array( $this, 'enqueue_frontend_styles' ) );
        add_action( 'wp_ajax_rbt_queue_translations', array( $this, 'ajax_queue_translations' ) );
        add_action( 'wp_ajax_rbt_retranslate', array( $this, 'ajax_retranslate' ) );
        add_action( 'wp_ajax_rbt_save_settings', array( $this, 'ajax_save_settings' ) );
        add_action( 'wp_ajax_rbt_get_statuses', array( $this, 'ajax_get_statuses' ) );
        add_action( 'wp_ajax_rbt_get_queue_summary', array( $this, 'ajax_get_queue_summary' ) );
        add_action( 'wp_ajax_rbt_get_queue_items', array( $this, 'ajax_get_queue_items' ) );
        add_action( 'wp_ajax_rbt_cancel_translation', array( $this, 'ajax_cancel_translation' ) );
        add_action( 'wp_ajax_rbt_retry_translation', array( $this, 'ajax_retry_translation' ) );
        add_action( 'wp_ajax_rbt_run_now', array( $this, 'ajax_run_now' ) );
        add_action( 'wp_ajax_rbt_requeue_out_of_date', array( $this, 'ajax_requeue_out_of_date' ) );
        add_action( 'wp_ajax_rbt_fix_internal_links', array( $this, 'ajax_fix_internal_links' ) );
        add_action( 'wp_ajax_rbt_search_sources', array( $this, 'ajax_search_sources' ) );
        add_action( 'wp_ajax_rbt_add_source_root', array( $this, 'ajax_add_source_root' ) );
        add_action( 'wp_ajax_rbt_remove_source_root', array( $this, 'ajax_remove_source_root' ) );
        add_action( 'wp_ajax_rbt_get_log', array( $this, 'ajax_get_log' ) );
        add_action( 'wp_ajax_rbt_clear_log', array( $this, 'ajax_clear_log' ) );
        add_action( 'wp_ajax_rbt_clear_completed', array( $this, 'ajax_clear_completed' ) );
        add_action( 'wp_ajax_rbt_test_model', array( $this, 'ajax_test_model' ) );
        add_action( 'wp_ajax_rbt_save_menu_labels', array( $this, 'ajax_save_menu_labels' ) );

        add_action( 'rbt_translator_process_queue', array( $this, 'process_queue' ) );

        add_filter( 'query_vars', array( $this, 'add_query_vars' ) );
        add_action( 'init', array( $this, 'add_rewrite_rules' ) );
        add_action( 'parse_request', array( $this, 'handle_lang_routes' ), 1 );
        add_action( 'wp_head', array( $this, 'output_rbt_lang_meta' ) );
        add_action( 'wp_body_open', array( $this, 'output_rbt_lang_body_marker' ) );
        add_filter( 'redirect_canonical', array( $this, 'disable_lang_canonical_redirect' ), 10, 2 );
        add_filter( 'page_link', array( $this, 'filter_page_link' ), 10, 3 );
        add_filter( 'post_link', array( $this, 'filter_post_link' ), 10, 3 );
        add_filter( 'the_content', array( $this, 'filter_content_links' ), 20 );

        // Frontend: show available translations under the post/page title
        add_filter( 'the_title', array( $this, 'filter_title_with_translation_links' ), 20, 2 );

        // Nav menu filters
        add_filter( 'nav_menu_link_attributes', array( $this, 'filter_nav_menu_link' ), 10, 4 );
        add_filter( 'nav_menu_item_title', array( $this, 'filter_nav_menu_item_title' ), 10, 4 );
        add_filter( 'wp_nav_menu_items', array( $this, 'filter_nav_menu_items_html' ), 10, 2 );

        // Publish translations actions
        add_action( 'wp_ajax_rbt_publish_translations', array( $this, 'ajax_publish_translations' ) );
        add_action( 'wp_ajax_rbt_publish_all_drafts', array( $this, 'ajax_publish_all_drafts' ) );
        add_action( 'wp_ajax_rbt_repair_video', array( $this, 'ajax_repair_video' ) );
        add_action( 'wp_ajax_rbt_delete_translations', array( $this, 'ajax_delete_translations' ) );
        add_action( 'save_post', array( $this, 'on_source_saved' ), 10, 3 );

        // Public REST API for translated URL lookups (used by React frontpage)
        add_action( 'rest_api_init', array( $this, 'register_rest_routes' ) );
    }

    private function get_available_translations_for_source( $source_post_id ) {
        $source_post_id = intval( $source_post_id );
        if ( $source_post_id <= 0 ) {
            return array();
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';

        // Only translations that have been created and are marked completed.
        $rows = $wpdb->get_results( $wpdb->prepare(
            "SELECT lang, translated_post_id, status FROM {$table} WHERE source_post_id=%d AND status=%s AND translated_post_id IS NOT NULL AND translated_post_id!=0 ORDER BY lang ASC",
            $source_post_id,
            'completed'
        ) );

        if ( empty( $rows ) ) {
            return array();
        }

        $out = array();
        foreach ( $rows as $r ) {
            $lang = sanitize_text_field( $r->lang );
            $tid = intval( $r->translated_post_id );
            if ( ! $lang || ! $tid ) continue;
            $out[ $lang ] = $tid;
        }
        return $out;
    }

    private function render_translation_links_inline( $source_post_id, $current_lang, $current_post_id ) {
        $langs = $this->languages();
        $source_post_id = intval( $source_post_id );
        $current_post_id = intval( $current_post_id );
        $current_lang = $current_lang ? sanitize_text_field( $current_lang ) : 'en';

        // Gather completed translations and always include English source.
        $translations = $this->get_available_translations_for_source( $source_post_id );

        // If there are no translations at all, do not render anything.
        if ( empty( $translations ) ) {
            return '';
        }

        $links = array();
        $has_non_english = false;

        // English (source) link.
        $en_label = isset( $langs['en'] ) ? $langs['en'] : 'English';
        $en_url = get_permalink( $source_post_id );
        if ( $en_url ) {
            $is_current = ( $current_lang === 'en' && $current_post_id === $source_post_id );
            $links[] = '<a class="rbt-translation-link' . ( $is_current ? ' is-current' : '' ) . '" href="' . esc_url( $en_url ) . '">' . esc_html( $en_label ) . '</a>';
        }

        // Other language links.
        foreach ( $translations as $code => $tid ) {
            $label = isset( $langs[ $code ] ) ? $langs[ $code ] : strtoupper( $code );
            $url = get_permalink( $tid );
            if ( ! $url ) continue;
            $is_current = ( $current_lang === $code && $current_post_id === $tid );
            $links[] = '<a class="rbt-translation-link' . ( $is_current ? ' is-current' : '' ) . '" href="' . esc_url( $url ) . '">' . esc_html( $label ) . '</a>';
            $has_non_english = true;
        }

        // If no non-English translation links exist, do not show.
        if ( ! $has_non_english ) {
            return '';
        }

        return '<span class="rbt-translation-links" aria-label="Translations">' . implode( ' · ', $links ) . '</span>';
    }

    public function filter_title_with_translation_links( $title, $post_id ) {
        if ( is_admin() || is_feed() ) {
            return $title;
        }

        // Only apply on singular post/page views, not in widgets or other contexts
        if ( ! is_singular() ) {
            return $title;
        }

        $post_id = intval( $post_id );
        if ( $post_id <= 0 ) {
            return $title;
        }

        // Only apply to the main queried post, not to titles in widgets or related posts
        if ( absint( get_queried_object_id() ) !== $post_id ) {
            return $title;
        }

        $ptype = get_post_type( $post_id );
        if ( ! in_array( $ptype, array( 'post', 'page' ), true ) ) {
            return $title;
        }

        // Avoid double-injection.
        if ( strpos( $title, '<!--rbt-trans-links-->' ) !== false ) {
            return $title;
        }

        // Determine source and current language.
        $meta_source_id = intval( get_post_meta( $post_id, 'rbt_source_id', true ) );
        $meta_lang = sanitize_text_field( get_post_meta( $post_id, 'rbt_lang', true ) );

        $source_id = $meta_source_id ? $meta_source_id : $post_id;
        $current_lang = $meta_lang ? $meta_lang : 'en';

        $links_html = $this->render_translation_links_inline( $source_id, $current_lang, $post_id );
        if ( empty( $links_html ) ) {
            return $title;
        }

        // Render under the title text using CSS for styling.
        return $title . '<!--rbt-trans-links-->' . $links_html;
    }

    public function activate() {
        $this->create_tables();
        $this->add_rewrite_rules();
        flush_rewrite_rules();
    }

    private function create_tables() {
        global $wpdb;
        require_once ABSPATH . 'wp-admin/includes/upgrade.php';

        $table = $wpdb->prefix . 'rbt_translations';
        $charset = $wpdb->get_charset_collate();

        $sql = "CREATE TABLE {$table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            source_post_id BIGINT UNSIGNED NOT NULL,
            lang VARCHAR(8) NOT NULL,
            translated_post_id BIGINT UNSIGNED NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            attempts INT NOT NULL DEFAULT 0,
            next_retry DATETIME NULL,
            last_translated DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uniq_source_lang (source_post_id, lang),
            KEY idx_lang_status (lang, status),
            KEY idx_next_retry (next_retry)
        ) {$charset};";

        $batch_table = $wpdb->prefix . 'rbt_openai_batches';
        $sql2 = "CREATE TABLE {$batch_table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            batch_id VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'submitted',
            items_json LONGTEXT NULL,
            output_file_id VARCHAR(64) NULL,
            error TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uniq_batch_id (batch_id)
        ) {$charset};";

        dbDelta( $sql );
        dbDelta( $sql2 );
    }

    // Restore or repair translation index rows from existing translated posts (prevents data loss when rows are deleted).
    private function repair_translation_index() {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';

        $translated_posts = get_posts( array(
            'post_type'      => array( 'post', 'page' ),
            'posts_per_page' => -1,
            'post_status'    => array( 'publish', 'draft', 'private' ),
            'meta_query'     => array(
                array( 'key' => 'rbt_source_id', 'compare' => 'EXISTS' ),
                array( 'key' => 'rbt_lang', 'compare' => 'EXISTS' ),
            ),
            'fields'         => 'ids',
            'no_found_rows'  => true,
        ) );

        if ( empty( $translated_posts ) ) {
            return;
        }

        $restored = 0;
        $updated = 0;

        foreach ( $translated_posts as $tid ) {
            $source_id = intval( get_post_meta( $tid, 'rbt_source_id', true ) );
            $lang = sanitize_text_field( get_post_meta( $tid, 'rbt_lang', true ) );
            if ( ! $source_id || ! $lang ) continue;

            $row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE source_post_id=%d AND lang=%s", $source_id, $lang ) );
            $last = get_post_modified_time( 'Y-m-d H:i:s', true, $tid );

            if ( ! $row ) {
                $wpdb->insert( $table, array(
                    'source_post_id'      => $source_id,
                    'lang'                => $lang,
                    'translated_post_id'  => $tid,
                    'status'              => 'completed',
                    'attempts'            => 0,
                    'next_retry'          => null,
                    'last_translated'     => $last ? $last : current_time( 'mysql' ),
                ) );
                $restored++;
                continue;
            }

            $updates = array();
            if ( empty( $row->translated_post_id ) ) {
                $updates['translated_post_id'] = $tid;
            }
            if ( $row->status !== 'completed' ) {
                $updates['status'] = 'completed';
            }
            if ( empty( $row->last_translated ) && $last ) {
                $updates['last_translated'] = $last;
            }

            if ( ! empty( $updates ) ) {
                $wpdb->update( $table, $updates, array( 'id' => $row->id ) );
                $updated++;
            }
        }

        if ( $restored || $updated ) {
            $this->log( 'repair_translation_index', array( 'restored' => $restored, 'updated' => $updated ) );
        }
    }

    public function admin_menu() {
        // Ensure tables/columns are present when admin opens the page (safe to run dbDelta)
        $this->create_tables();

        add_menu_page(
            'RBT Translator',
            'RBT Translator',
            'manage_options',
            'rbt-translator',
            array( $this, 'render_admin_page' ),
            'dashicons-translation',
            65
        );

        // Submenu for menu label translations
        add_submenu_page(
            'rbt-translator',
            'Menu Label Translations',
            'Menu Labels',
            'manage_options',
            'rbt-translator-menu-labels',
            array( $this, 'render_menu_label_page' )
        );
    }

    public function admin_assets( $hook ) {
        // Enqueue assets for both the main translator page and the menu-labels subpage
        if ( strpos( $hook, 'rbt-translator' ) === false ) {
            return;
        }
        wp_enqueue_style( 'rbt-translator-admin', RBT_TRANSLATOR_URL . 'admin.css', array(), RBT_TRANSLATOR_VERSION );
        wp_enqueue_script( 'rbt-translator-admin', RBT_TRANSLATOR_URL . 'admin.js', array( 'jquery' ), RBT_TRANSLATOR_VERSION, true );

        wp_localize_script( 'rbt-translator-admin', 'rbtTranslator', array(
            'ajaxUrl' => admin_url( 'admin-ajax.php' ),
            'nonce' => wp_create_nonce( 'rbt_translator_nonce' ),
            'adminUrl' => admin_url( 'admin.php' ),
            'pageUrl' => admin_url( 'admin.php?page=rbt-translator' ),
        ) );
    }

    public function enqueue_frontend_styles() {
        if ( is_admin() ) {
            return;
        }
        wp_enqueue_style( 'rbt-translator-frontend', RBT_TRANSLATOR_URL . 'frontend.css', array(), RBT_TRANSLATOR_VERSION );
    }

    private function languages() {
        return array(
            'en' => 'English',
            'hr' => 'Hrvatski',
            'sr' => 'Српски',
            'he' => 'עברית',
            'el' => 'Ελληνικά',
            'es' => 'Español',
            'fr' => 'Français',
            'de' => 'Deutsch',
            'it' => 'Italiano',
            'pt' => 'Português',
            'ru' => 'Русский',
            'ar' => 'العربية',
            'zh' => '中文',
            'hi' => 'हिन्दी',
            'pl' => 'Polski',
            'uk' => 'Українська',
            'ro' => 'Română',
            'nl' => 'Nederlands',
            'sv' => 'Svenska',
            'hu' => 'Magyar',
            'cs' => 'Čeština',
            'tr' => 'Türkçe',
            'ja' => '日本語',
            'ko' => '한국어',
            'vi' => 'Tiếng Việt',
            'th' => 'ไทย',
            'id' => 'Bahasa Indonesia',
            'bn' => 'বাংলা',
            'ur' => 'اردو',
            'fa' => 'فارسی',
            'pa' => 'ਪੰਜਾਬੀ',
            'mr' => 'मराठी',
            'ta' => 'தமிழ்',
            'sw' => 'Kiswahili',
            'ha' => 'Hausa',
            'yo' => 'Yorùbá',
            'ig' => 'Igbo',
            'am' => 'አማርኛ',
            'om' => 'Afaan Oromoo'
        );
    }

    private function get_settings() {
        $defaults = array(
            'gemini_keys' => '',
            'gemini_model' => 'gemini-3-flash-preview',
            'target_status' => 'publish',
            'batch_size' => 3,
            'auto_publish_on_source_publish' => false,
            'model_provider' => 'gemini',
            'openai_api_key' => '',
            'openai_model' => 'gpt-4.1-mini',
            'openai_batch_mode' => false,
            'openai_batch_size' => 20,
            'openai_batch_window' => '24h',
            'menu_label_translations' => json_encode( array(
                'Stats' => array( 'es' => 'Estadísticas' ),
                'Notes' => array( 'es' => 'Notas' ),
                'Methodology' => array( 'es' => 'Metodología' ),
                'About' => array( 'es' => 'Acerca de' ),
            ) ), // Default Spanish shortcuts for common menu labels
        );
        $saved = get_option( 'rbt_translator_settings', array() );
        return wp_parse_args( $saved, $defaults );
    }

    public function render_admin_page() {
        // Rebuild any missing translation rows from existing translated posts to avoid losing tracking.
        $this->repair_translation_index();

        $settings = $this->get_settings();
        $languages = $this->languages();

        $query_args = array(
            'post_type'      => array( 'page', 'post' ),
            'posts_per_page' => -1,
            'post_status'    => array( 'publish', 'draft', 'private' ),
            'orderby'        => 'modified',
            'order'          => 'DESC',
            'meta_query'     => array(
                array(
                    'key'     => 'rbt_source_root',
                    'value'   => '1',
                    'compare' => '=',
                )
            ),
        );

        $query = new WP_Query( $query_args );
        $posts = $query->posts;

        $translation_map = $this->get_translation_map();

        // Get real-time queue counts from DB to avoid "0 queued" flash on page load.
        global $wpdb;
        $_table = $wpdb->prefix . 'rbt_translations';
        $_counts_raw = $wpdb->get_results( "SELECT status, COUNT(*) as c FROM {$_table} GROUP BY status" );
        $_counts = array();
        foreach ( $_counts_raw as $_c ) {
            $_counts[ $_c->status ] = intval( $_c->c );
        }
        $_q   = $_counts['queued']     ?? 0;
        $_p   = $_counts['processing'] ?? 0;
        $_f   = $_counts['failed']     ?? 0;
        $_initial_count_label = esc_html( "{$_q} queued · {$_p} processing · {$_f} failed" );
        $_show_queue_panel    = ( $_q > 0 || $_p > 0 ) ? '' : 'display:none; ';
        $last_run = get_option( 'rbt_last_run', 'never' );
        ?>
        <div class="wrap rbt-translator">
            <h1>RBT Translator</h1>
            <div class="rbt-queue-overview" id="rbt-queue-overview">
                <div class="rbt-queue-summary">
                    <strong>Queue:</strong> <span id="rbt-queue-count"><?php echo $_initial_count_label; ?></span>
                    &nbsp;•&nbsp; <strong>Last run:</strong> <span id="rbt-last-run"><?php echo esc_html( $last_run ); ?></span>
                </div>
                <div class="rbt-queue-controls">
                    <button class="button" id="rbt-view-queue">View Queue</button>
                    <button class="button" id="rbt-view-log">View Log</button>
                    <button class="button button-secondary" id="rbt-run-now">Run Now</button>
                    <button class="button button-secondary" id="rbt-requeue-outdated">Re-queue Out-of-date</button>
                    <button class="button button-secondary" id="rbt-clear-completed">Clear completed (orphans only)</button>
                    <button class="button button-secondary" id="rbt-fix-internal-links">Fix Internal Links</button>
                </div>
            </div>

            <div class="rbt-queue-items" id="rbt-queue-items" style="<?php echo $_show_queue_panel; ?>margin:12px 0;">
                <h2>Queue Items</h2>
                <div class="rbt-queue-filters" style="display:flex; gap:8px; align-items:center; margin-bottom:8px; flex-wrap:wrap;">
                    <input type="search" id="rbt-queue-search" placeholder="Filter by title/lang" style="min-width:220px;">
                    <select id="rbt-queue-status-filter">
                        <option value="all">All statuses</option>
                        <option value="queued">Queued</option>
                        <option value="processing">Processing</option>
                        <option value="failed">Failed</option>
                        <option value="completed">Completed</option>
                        <option value="cancelled">Cancelled</option>
                    </select>
                    <label style="display:flex; align-items:center; gap:4px;">
                        <input type="checkbox" id="rbt-queue-autorefresh" checked> Auto-refresh (5s)
                    </label>
                    <button class="button" id="rbt-queue-refresh">Refresh now</button>
                </div>
                <div id="rbt-queue-table-wrap"></div>
            </div>

            <div class="rbt-log-viewer" id="rbt-log-viewer" style="display:none; margin:12px 0;">
                <h2>Process Log</h2>
                <button class="button" id="rbt-clear-log">Clear Log</button>
                <div id="rbt-log-wrap" style="max-height:600px; overflow-y:auto; background:#f9f9f9; padding:12px; border:1px solid #ddd; font-family:monospace; font-size:12px; white-space:pre-wrap;"></div>
            </div>

            <div class="rbt-sources">
                <h2>Manage Sources</h2>
                <p class="description">Add the pages/posts you want as translation roots. Only these sources appear below.</p>
                <div style="display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap;">
                    <button class="button" id="rbt-publish-all-drafts" title="Publish all completed translations that are still in draft status">Publish All Drafts</button>
                    <button class="button" id="rbt-repair-video" title="Restore video/audio blocks that were stripped during translation">Repair Video/Media</button>
                </div>
                <div class="rbt-source-search">
                    <input type="search" id="rbt-source-search" placeholder="Search posts/pages...">
                    <button class="button" id="rbt-source-search-btn">Search</button>
                </div>
                <div id="rbt-source-results" class="rbt-source-results"></div>
            </div>

            <div class="rbt-settings">
                <h2>Settings</h2>

                <h3>Model Provider</h3>
                <label>Provider</label>
                <select id="rbt-model-provider">
                    <option value="gemini" <?php selected( $settings['model_provider'], 'gemini' ); ?>>Gemini</option>
                    <option value="openai" <?php selected( $settings['model_provider'], 'openai' ); ?>>OpenAI (GPT)</option>
                </select>
                <p class="description"><strong>Note:</strong> Gemini uses the runner's per-run batch size for processing. OpenAI supports two modes: direct (per-run translations) and Batch API (asynchronous). OpenAI-specific batch settings are shown below when you select OpenAI.</p>

                <div id="rbt-gemini-settings" style="margin-top:12px;">
                    <h3>Gemini Settings</h3>
                    <label>Gemini API Keys (comma-separated)</label>
                    <textarea id="rbt-gemini-keys" rows="3" placeholder="key1,key2,..."><?php echo esc_textarea( $settings['gemini_keys'] ); ?></textarea>

                    <label>Gemini Model</label>
                    <div style="display:flex; gap:8px; align-items:center;">
                        <select id="rbt-gemini-model-select">
                            <option value="gemini-3-flash-preview" <?php selected( $settings['gemini_model'], 'gemini-3-flash-preview' ); ?>>gemini-3-flash-preview</option>
                            <option value="gemini-3-flash" <?php selected( $settings['gemini_model'], 'gemini-3-flash' ); ?>>gemini-3-flash</option>
                            <option value="gemini-2.5-flash" <?php selected( $settings['gemini_model'], 'gemini-2.5-flash' ); ?>>gemini-2.5-flash</option>
                            <option value="gemini-2.5-flash-lite" <?php selected( $settings['gemini_model'], 'gemini-2.5-flash-lite' ); ?>>gemini-2.5-flash-lite</option>
                            <option value="custom">Custom...</option>
                        </select>
                        <input type="text" id="rbt-gemini-model" value="<?php echo esc_attr( $settings['gemini_model'] ); ?>" placeholder="custom model" />
                        <button class="button" id="rbt-test-model">Test Model</button>
                    </div>
                    <p class="description">Set the model name (e.g., <code>gemini-3-flash-preview</code> or <code>gemini-2.5-flash</code>). The plugin strips a leading <code>models/</code> automatically.</p>
                    <p><strong>Current model:</strong> <span id="rbt-current-model"><?php echo esc_html( $settings['gemini_model'] ); ?></span> <span id="rbt-test-result" style="margin-left:12px;color:#666;font-size:90%;"></span></p>

                    <label>Gemini Request Timeout (seconds)</label>
                    <input type="number" id="rbt-gemini-timeout" min="10" max="600" value="<?php echo esc_attr( isset( $settings['gemini_timeout'] ) ? $settings['gemini_timeout'] : 60 ); ?>" />
                    <p class="description">How many seconds to wait for Gemini API responses. Increase for large documents or slow networks. Default 60s.</p>
                </div>

                <div id="rbt-openai-settings" style="margin-top:12px;">
                    <h3>OpenAI (GPT) Settings</h3>
                    <label>OpenAI API Key</label>
                    <input type="password" id="rbt-openai-key" value="<?php echo esc_attr( $settings['openai_api_key'] ); ?>" placeholder="sk-..." />
                    <p class="description">Store your OpenAI API key here (kept in WordPress options).</p>

                    <label>OpenAI Model</label>
                    <div style="display:flex; gap:8px; align-items:center;">
                        <select id="rbt-openai-model">
                            <option value="gpt-5.1-chat-latest" <?php selected( $settings['openai_model'], 'gpt-5.1-chat-latest' ); ?>>gpt-5.1-chat-latest</option>
                            <option value="gpt-4.1-mini" <?php selected( $settings['openai_model'], 'gpt-4.1-mini' ); ?>>gpt-4.1-mini</option>
                            <option value="gpt-4.1" <?php selected( $settings['openai_model'], 'gpt-4.1' ); ?>>gpt-4.1</option>
                            <option value="gpt-4o-mini" <?php selected( $settings['openai_model'], 'gpt-4o-mini' ); ?>>gpt-4o-mini</option>
                            <option value="gpt-4o" <?php selected( $settings['openai_model'], 'gpt-4o' ); ?>>gpt-4o</option>
                        </select>
                        <button class="button" id="rbt-test-model-openai">Test Model</button>
                    </div>
                    <p><strong>Current OpenAI model:</strong> <span id="rbt-openai-current-model"><?php echo esc_html( $settings['openai_model'] ); ?></span></p>

                    <label style="margin-top:8px;"><input type="checkbox" id="rbt-openai-batch-mode" value="1" <?php checked( $settings['openai_batch_mode'], true ); ?>> Enable OpenAI Batch API</label>
                    <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
                        <label for="rbt-openai-batch-size" style="margin:0;">OpenAI Batch size (items per OpenAI batch)</label>
                        <input type="number" id="rbt-openai-batch-size" min="1" max="200" value="<?php echo esc_attr( $settings['openai_batch_size'] ); ?>">
                        <label for="rbt-openai-batch-window" style="margin:0;">Completion window</label>
                        <select id="rbt-openai-batch-window">
                            <option value="24h" <?php selected( $settings['openai_batch_window'], '24h' ); ?>>24h</option>
                        </select>
                    </div>
                    <p class="description"><strong>OpenAI Batch:</strong> When enabled, queued translations are grouped into JSONL batches and uploaded to OpenAI's Batch API. Results arrive asynchronously and are applied when batches complete. Use the <em>OpenAI Batch size</em> to control how many items are submitted per OpenAI batch.</p>
                </div>

                <label>Per-run Batch Size (items processed per runner run)</label>
                <input type="number" id="rbt-batch-size" min="1" max="10" value="<?php echo esc_attr( $settings['batch_size'] ); ?>">
                <p class="description">Controls how many queued items the runner picks each cycle. If <strong>OpenAI Batch API</strong> is enabled, the runner will submit up to <code>min(per-run, OpenAI Batch size)</code> items per batch. For Gemini and OpenAI direct (non-batch) mode, this controls how many items are processed directly each run.</p>

                <label><input type="checkbox" id="rbt-auto-publish" value="1" <?php checked( $settings['auto_publish_on_source_publish'], true ); ?>> Auto-publish translations when a source is published</label>
                <p class="description">When enabled, any existing translations for a source will be set to <strong>Publish</strong> when the source post is published.</p>

                <h3>Gemini Key Status</h3>
                <div class="rbt-key-status" id="rbt-key-status">
                    <?php
                        $keys_list = array_filter( array_map( 'trim', explode( ',', $settings['gemini_keys'] ) ) );
                        if ( empty( $keys_list ) ) {
                            echo '<div>No keys configured</div>';
                        } else {
                            echo '<table style="width:100%; border-collapse:collapse; margin-bottom:10px;"><thead><tr><th>Key (prefix)</th><th>Usage (last ~60s)</th><th>Next available</th></tr></thead><tbody>';
                            foreach ( $keys_list as $k ) {
                                $count = $this->key_usage_count( $k );
                                $next = $this->get_key_next_available( $k );
                                $next_str = $next ? date( 'Y-m-d H:i:s', $next ) : '';
                                echo '<tr><td>' . esc_html( substr( $k, 0, 10 ) ) . '...</td><td>' . intval( $count ) . '</td><td>' . esc_html( $next_str ) . '</td></tr>';
                            }
                            echo '</tbody></table>';
                        }
                    ?>
                </div>

                <button class="button button-primary" id="rbt-save-settings">Save Settings</button>
                <div class="rbt-status" id="rbt-settings-status"></div>
            </div>

            <div class="rbt-settings">
                <h2>Menu Label Translations</h2>
                <p class="description">Manage menu label translations on the <a href="<?php echo esc_url( admin_url( 'admin.php?page=rbt-translator-menu-labels' ) ); ?>">Menu Labels</a> page.</p>
            </div>

            <div class="rbt-batch">
                <h2>Batch Translate</h2>
                <div class="rbt-batch-controls">
                    <select id="rbt-language-select">
                        <?php foreach ( $languages as $code => $label ) : if ( $code === 'en' ) continue; ?>
                            <option value="<?php echo esc_attr( $code ); ?>"><?php echo esc_html( $label ); ?></option>
                        <?php endforeach; ?>
                    </select>
                    <button class="button button-secondary" id="rbt-queue-selected">Queue Selected</button>
                    <span class="rbt-status" id="rbt-queue-status"></span>
                </div>
            </div>

            <div class="rbt-accordion">
                <h2>English Sources</h2>
                <?php foreach ( $posts as $post ) :
                    $per_lang = isset( $translation_map[ $post->ID ] ) ? $translation_map[ $post->ID ] : array();

                    // Compute header stats
                    $stat_up = 0; $stat_out = 0; $stat_translated = 0; $stat_not_translated = 0;
                    $stat_queued = 0; $stat_processing = 0; $stat_failed = 0;
                    $stat_published = 0; $stat_draft = 0;
                    foreach ( $languages as $lcode => $llabel ) {
                        if ( $lcode === 'en' ) continue;
                        $entry = isset( $per_lang[ $lcode ] ) ? $per_lang[ $lcode ] : null;
                        if ( ! $entry ) { $stat_not_translated++; continue; }
                        if ( $entry->status === 'queued' ) { $stat_queued++; continue; }
                        if ( $entry->status === 'processing' ) { $stat_processing++; continue; }
                        if ( $entry->status === 'failed' ) { $stat_failed++; continue; }
                        if ( $entry->status === 'completed' && ! empty( $entry->translated_post_id ) ) {
                            $stat_translated++;
                            // Count published vs draft based on translated post status
                            $t_post = get_post( intval( $entry->translated_post_id ) );
                            if ( $t_post && isset( $t_post->post_status ) && $t_post->post_status === 'publish' ) {
                                $stat_published++;
                            } else {
                                $stat_draft++;
                            }

                            // Prefer the recorded last_translated timestamp (DB) but also consider the translated post's modified time.
                            $s_mod = get_post_modified_time( 'U', true, $post->ID );
                            $translated_time = 0;
                            if ( ! empty( $entry->last_translated ) ) {
                                $translated_time = strtotime( $entry->last_translated );
                            }
                            $t_mod = get_post_modified_time( 'U', true, intval( $entry->translated_post_id ) );
                            if ( $t_mod ) {
                                $translated_time = max( $translated_time, $t_mod );
                            }
                            if ( $translated_time && $s_mod && $translated_time >= $s_mod ) {
                                $stat_up++;
                            } else {
                                $stat_out++;
                            }
                        } else {
                            $stat_not_translated++;
                        }
                    }
                    // Determine main status badge
                    $total_targets = count( $languages ) - 1; // excluding en
                    $main_status_label = 'Up to date';
                    $main_status_class = 'rbt-badge-up';
                    
                    if ( $stat_failed > 0 ) {
                        $main_status_label = 'Errors (' . $stat_failed . ')';
                        $main_status_class = 'rbt-badge-failed';
                    } elseif ( $stat_processing > 0 || $stat_queued > 0 ) {
                        $main_status_label = 'Processing...';
                        $main_status_class = 'rbt-badge-processing';
                    } elseif ( $stat_not_translated > 0 ) {
                        $main_status_label = 'Incomplete (' . ( $total_targets - $stat_not_translated ) . '/' . $total_targets . ')';
                        $main_status_class = 'rbt-badge-not';
                    } elseif ( $stat_out > 0 ) {
                        $main_status_label = 'Updates needed (' . $stat_out . ')';
                        $main_status_class = 'rbt-badge-out';
                    }

                    // Build summary tooltip
                    $summary_parts = array();
                    if ( $stat_up ) $summary_parts[] = "$stat_up up-to-date";
                    if ( $stat_out ) $summary_parts[] = "$stat_out out-of-date";
                    if ( $stat_not_translated ) $summary_parts[] = "$stat_not_translated missing";
                    if ( $stat_queued ) $summary_parts[] = "$stat_queued queued";
                    if ( $stat_processing ) $summary_parts[] = "$stat_processing processing";
                    if ( $stat_failed ) $summary_parts[] = "$stat_failed failed";
                    $summary_tooltip = implode( ', ', $summary_parts );
                    ?>
                    <div class="rbt-accordion-item" data-post-id="<?php echo esc_attr( $post->ID ); ?>">
                        <div class="rbt-accordion-header" style="flex-direction:column; align-items:stretch; gap:4px;">
                            <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
                                <div style="display:flex; align-items:center; gap:10px;">
                                    <input type="checkbox" class="rbt-select-post" value="<?php echo esc_attr( $post->ID ); ?>">
                                    <strong style="font-size:1.1em;"><?php echo esc_html( $post->post_title ); ?></strong>
                                </div>
                                <span class="rbt-meta" style="white-space:nowrap; margin-left:12px;"><?php echo esc_html( ucfirst( $post->post_type ) ); ?> · Updated <?php echo esc_html( get_the_modified_date( 'Y-m-d', $post ) ); ?></span>
                            </div>
                            <div style="display:flex; justify-content:space-between; align-items:center; width:100%; margin-top:4px; padding-top:4px; border-top:1px solid #eee;">
                                <div class="rbt-header-stats" style="margin-left:0; gap:8px;" data-post-id="<?php echo esc_attr( $post->ID ); ?>">
                                    <span class="rbt-badge <?php echo esc_attr( $main_status_class ); ?>" title="<?php echo esc_attr( $summary_tooltip ); ?>" style="font-weight:600; font-size:11px;">
                                        <?php echo esc_html( $main_status_label ); ?>
                                    </span>
                                    <div style="font-size:11px; color:#777;">
                                        <?php if ( $stat_published ) echo ' <span title="Published">Pub: ' . $stat_published . '</span>'; ?>
                                        <?php if ( $stat_draft ) echo ' <span title="Draft">Drft: ' . $stat_draft . '</span>'; ?>
                                    </div>
                                </div>
                                <div style="display:flex; gap:8px; align-items:center;">
                                    <a class="rbt-source-link" href="<?php echo esc_url( get_permalink( $post->ID ) ); ?>" target="_blank" rel="noopener noreferrer">View source</a>
                                    <button class="button button-small rbt-publish-translations" data-post-id="<?php echo esc_attr( $post->ID ); ?>" title="Publish all existing translations">Publish</button>
                                    <button class="button button-small rbt-delete-translations" data-post-id="<?php echo esc_attr( $post->ID ); ?>" style="color:#a00;" title="Delete all translations for this source">Delete Translations</button>
                                    <button class="button button-small rbt-remove-source" data-post-id="<?php echo esc_attr( $post->ID ); ?>" title="Stop tracking this source">Remove source</button>
                                </div>
                            </div>
                        </div>
                        <div class="rbt-accordion-body">
                            <div class="rbt-source">
                                <?php echo wp_kses_post( wp_trim_words( $post->post_content, 60 ) ); ?>
                            </div>
                            <div class="rbt-language-grid">
                                <?php foreach ( $languages as $code => $label ) : if ( $code === 'en' ) continue; ?>
                                    <?php
                                        $entry = isset( $per_lang[ $code ] ) ? $per_lang[ $code ] : null;
                                        $status = $entry ? $entry->status : 'not translated';
                                        $last = '';
                                        if ( $entry && $entry->last_translated ) {
                                            $last = $entry->last_translated;
                                        } elseif ( $entry && ! empty( $entry->translated_post_id ) ) {
                                            $last_mod = get_post_modified_time( 'Y-m-d H:i:s', true, intval( $entry->translated_post_id ) );
                                            $last = $last_mod ? $last_mod : '';
                                        }

                                        $known = array( 'queued', 'processing', 'completed', 'failed' );
                                        if ( in_array( $status, $known, true ) ) {
                                            $status_class = 'status-' . $status;
                                        } elseif ( $status === 'not translated' ) {
                                            $status_class = 'status-not-translated';
                                        } else {
                                            $status_class = 'status-unknown';
                                        }

                                        $source_modified = get_post_modified_time( 'U', true, $post->ID );
                                        $translated_modified = 0;
                                        $translation_complete = $entry && $entry->status === 'completed' && ! empty( $entry->translated_post_id );
                                        if ( $translation_complete ) {
                                            // Use the recorded last_translated timestamp if available; otherwise rely on the translated post's modified time.
                                            $translated_time = 0;
                                            if ( ! empty( $entry->last_translated ) ) {
                                                $translated_time = strtotime( $entry->last_translated );
                                            }
                                            $t_mod = get_post_modified_time( 'U', true, intval( $entry->translated_post_id ) );
                                            if ( $t_mod ) {
                                                $translated_time = max( $translated_time, $t_mod );
                                            }
                                            if ( $translated_time && $translated_time >= $source_modified ) {
                                                $freshness_label = 'up to date';
                                                $freshness_class = 'status-up-to-date';
                                            } else {
                                                $freshness_label = 'out of date';
                                                $freshness_class = 'status-out-of-date';
                                            }
                                        } else {
                                            $freshness_label = 'not complete';
                                            $freshness_class = 'status-not-complete';
                                        }
                                    ?>
                                    <div class="rbt-language-card <?php echo esc_attr( $status_class . ' ' . $freshness_class ); ?>" data-lang="<?php echo esc_attr( $code ); ?>" data-status="<?php echo esc_attr( $status ); ?>" data-freshness="<?php echo esc_attr( $freshness_label ); ?>">
                                        <div class="rbt-lang-label"><?php echo esc_html( $label ); ?></div>
                                        <?php
                                            $perm = '';
                                            if ( $translation_complete && ! empty( $entry->translated_post_id ) ) {
                                                $perm = get_permalink( intval( $entry->translated_post_id ) );
                                            }
                                        ?>
                                        <a class="rbt-lang-status" href="<?php echo esc_url( $perm ? $perm : '#' ); ?>" data-permalink="<?php echo esc_attr( $perm ); ?>" target="_blank" rel="noopener noreferrer"><?php echo esc_html( $freshness_label ); ?></a>
                                        <div class="rbt-lang-date"><?php echo esc_html( $last ); ?></div>
                                        <button class="button button-small rbt-retranslate" data-lang="<?php echo esc_attr( $code ); ?>">Translate / Retranslate</button>
                                    </div>
                                <?php endforeach; ?>
                            </div>
                        </div>
                    </div>
                <?php endforeach; ?>
            </div>
        </div>
        <?php
    }

    public function render_menu_label_page() {
        $settings = $this->get_settings();
        $menu_json = isset( $settings['menu_label_translations'] ) ? $settings['menu_label_translations'] : '';
        $menu_pretty = $menu_json;
        if ( ! empty( $menu_json ) ) {
            $decoded = json_decode( wp_unslash( $menu_json ), true );
            if ( is_array( $decoded ) ) {
                $menu_pretty = json_encode( $decoded, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE );
            }
        }
        ?>
        <div class="wrap rbt-translator rbt-menu-labels">
            <h1>Menu Label Translations</h1>
            <p class="description">Provide a JSON map of source label → language → translated label. Used by the primary menu to show translated labels quickly.</p>
            <div style="display:flex; gap:16px; align-items:flex-start;">
                <div style="flex:1 1 50%;">
                    <label for="rbt-menu-labels-json"><strong>Primary Menu Labels</strong></label>
                    <textarea id="rbt-menu-labels-json" rows="12" style="width:100%; font-family:monospace; font-size:13px;"><?php echo esc_textarea( $menu_pretty ); ?></textarea>
                    <div style="margin-top:8px; display:flex; gap:8px; align-items:center;">
                        <button class="button button-primary" id="rbt-save-menu-labels">Save</button>
                        <span class="rbt-status" id="rbt-menu-label-status"></span>
                    </div>
                </div>

                <div style="flex:1 1 50%;">
                    <?php
                    $footer_json = isset( $settings['footer_menu_label_translations'] ) ? $settings['footer_menu_label_translations'] : '';
                    $footer_pretty = $footer_json;
                    if ( ! empty( $footer_json ) ) {
                        $decodedf = json_decode( wp_unslash( $footer_json ), true );
                        if ( is_array( $decodedf ) ) {
                            $footer_pretty = json_encode( $decodedf, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE );
                        }
                    }
                    ?>
                    <label for="rbt-footer-menu-labels-json"><strong>Footer Menu Labels</strong></label>
                    <textarea id="rbt-footer-menu-labels-json" rows="12" style="width:100%; font-family:monospace; font-size:13px;"><?php echo esc_textarea( $footer_pretty ); ?></textarea>
                    <div style="margin-top:8px; display:flex; gap:8px; align-items:center;">
                        <span class="rbt-status" id="rbt-footer-menu-label-status"></span>
                    </div>
                </div>
            </div>
        </div>
        <?php
    }

    public function ajax_save_menu_labels() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $menu_json = isset( $_POST['menu_labels'] ) ? trim( wp_unslash( $_POST['menu_labels'] ) ) : '';
        $footer_json = isset( $_POST['footer_menu_labels'] ) ? trim( wp_unslash( $_POST['footer_menu_labels'] ) ) : '';

        if ( $menu_json ) {
            $decoded = json_decode( $menu_json, true );
            if ( json_last_error() !== JSON_ERROR_NONE ) {
                wp_send_json_error( array( 'message' => 'Invalid JSON for Primary Menu: ' . json_last_error_msg() ) );
            }
            // normalize and store compact JSON
            $menu_json = wp_slash( json_encode( $decoded, JSON_UNESCAPED_UNICODE ) );
        } else {
            $menu_json = '';
        }

        if ( $footer_json ) {
            $decodedf = json_decode( $footer_json, true );
            if ( json_last_error() !== JSON_ERROR_NONE ) {
                wp_send_json_error( array( 'message' => 'Invalid JSON for Footer Menu: ' . json_last_error_msg() ) );
            }
            $footer_json = wp_slash( json_encode( $decodedf, JSON_UNESCAPED_UNICODE ) );
        } else {
            $footer_json = '';
        }

        $settings = $this->get_settings();
        $settings['menu_label_translations'] = $menu_json;
        $settings['footer_menu_label_translations'] = $footer_json;
        update_option( 'rbt_translator_settings', $settings );
        $this->log( 'ajax_save_menu_labels', array( 'labels_count' => ( $menu_json ? count( (array) json_decode( $menu_json, true ) ) : 0 ), 'footer_labels_count' => ( $footer_json ? count( (array) json_decode( $footer_json, true ) ) : 0 ) ) );
        wp_send_json_success( array( 'message' => 'Menu labels saved' ) );
    }

    private function get_translation_map() {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows = $wpdb->get_results( "SELECT * FROM {$table}" );
        $map = array();
        foreach ( $rows as $row ) {
            if ( ! isset( $map[ $row->source_post_id ] ) ) {
                $map[ $row->source_post_id ] = array();
            }
            $map[ $row->source_post_id ][ $row->lang ] = $row;
        }
        return $map;
    }

    public function ajax_save_settings() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        $keys = sanitize_textarea_field( wp_unslash( $_POST['gemini_keys'] ?? '' ) );
        $model = sanitize_text_field( wp_unslash( $_POST['gemini_model'] ?? 'gemini-3-flash-preview' ) );
        // Normalize model by stripping leading 'models/' if provided
        $model = preg_replace( '#^models/#', '', $model );
        $batch = intval( $_POST['batch_size'] ?? 3 );
        $auto_publish = isset( $_POST['auto_publish_on_source_publish'] ) && $_POST['auto_publish_on_source_publish'] == '1';
        $menu_trans = isset( $_POST['menu_label_translations'] ) ? trim( wp_unslash( $_POST['menu_label_translations'] ) ) : '';
        $provider = sanitize_text_field( wp_unslash( $_POST['model_provider'] ?? 'gemini' ) );
        $openai_key = sanitize_text_field( wp_unslash( $_POST['openai_api_key'] ?? '' ) );
        $openai_model = sanitize_text_field( wp_unslash( $_POST['openai_model'] ?? 'gpt-4.1-mini' ) );
        $openai_batch_mode = isset( $_POST['openai_batch_mode'] ) && $_POST['openai_batch_mode'] == '1';
        $openai_batch_size = intval( $_POST['openai_batch_size'] ?? 20 );
        $openai_batch_window = sanitize_text_field( wp_unslash( $_POST['openai_batch_window'] ?? '24h' ) );
        $gemini_timeout = intval( $_POST['gemini_timeout'] ?? 60 );

        // Validate JSON for menu label translations if provided
        if ( $menu_trans ) {
            $decoded = json_decode( $menu_trans, true );
            if ( json_last_error() !== JSON_ERROR_NONE ) {
                wp_send_json_error( array( 'message' => 'Invalid JSON for Menu Label Translations: ' . json_last_error_msg() ) );
            }
            // Normalize to compact JSON for storage
            $menu_trans = wp_slash( json_encode( $decoded, JSON_UNESCAPED_UNICODE ) );
        }

        $saved = array(
            'gemini_keys' => $keys,
            'gemini_model' => $model,
            'target_status' => 'publish',
            'batch_size' => max( 1, min( 10, $batch ) ),
            'auto_publish_on_source_publish' => $auto_publish,
            'menu_label_translations' => $menu_trans,
            'model_provider' => in_array( $provider, array( 'gemini', 'openai' ), true ) ? $provider : 'gemini',
            'openai_api_key' => $openai_key,
            'openai_model' => $openai_model,
            'openai_batch_mode' => $openai_batch_mode,
            'openai_batch_size' => max( 1, min( 200, $openai_batch_size ) ),
            'openai_batch_window' => in_array( $openai_batch_window, array( '24h' ), true ) ? $openai_batch_window : '24h',
            'gemini_timeout' => max( 10, min( 600, $gemini_timeout ) ),
        );

        update_option( 'rbt_translator_settings', $saved );

        $this->log( 'ajax_save_settings', array( 'saved_model' => $model, 'provider' => $saved['model_provider'], 'openai_model' => $openai_model, 'gemini_timeout' => $saved['gemini_timeout'], 'keys_count' => count( $keys ? explode( ',', $keys ) : array() ) ) );

        wp_send_json_success( array( 'message' => 'Settings saved', 'gemini_model' => $model, 'model_provider' => $saved['model_provider'], 'openai_model' => $openai_model, 'gemini_timeout' => $saved['gemini_timeout'] ) );
    }

    public function ajax_test_model() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        $provider = sanitize_text_field( wp_unslash( $_POST['provider'] ?? 'gemini' ) );
        $provider = in_array( $provider, array( 'gemini', 'openai' ), true ) ? $provider : 'gemini';
        $model = sanitize_text_field( wp_unslash( $_POST['model'] ?? '' ) );
        $model = preg_replace( '#^models/#', '', $model );
        if ( empty( $model ) ) {
            wp_send_json_error( array( 'message' => 'Missing model' ) );
        }

        $settings = $this->get_settings();
        $prompt = "Test: say OK";

        if ( $provider === 'openai' ) {
            $openai_key = isset( $settings['openai_api_key'] ) ? $settings['openai_api_key'] : '';
            if ( empty( $openai_key ) ) {
                wp_send_json_error( array( 'message' => 'No OpenAI API key configured' ) );
            }
            $resp = $this->call_openai( $prompt, $openai_key, $model );
            if ( is_array( $resp ) && isset( $resp['rate_limited'] ) ) {
                $this->log( 'ajax_test_model: rate limited', array( 'provider' => 'openai', 'model' => $model ) );
                wp_send_json_error( array( 'message' => 'Rate limited; try again shortly' ) );
            }
            if ( $resp ) {
                $this->log( 'ajax_test_model: success', array( 'provider' => 'openai', 'model' => $model ) );
                wp_send_json_success( array( 'message' => 'Model accepted', 'model' => $model ) );
            }
            $this->log( 'ajax_test_model: failed', array( 'provider' => 'openai', 'model' => $model ) );
            wp_send_json_error( array( 'message' => 'OpenAI request failed' ) );
        }

        $keys = array_filter( array_map( 'trim', explode( ',', $settings['gemini_keys'] ) ) );
        if ( empty( $keys ) ) {
            wp_send_json_error( array( 'message' => 'No Gemini API keys configured' ) );
        }

        foreach ( $keys as $key ) {
            $resp = $this->call_gemini( $prompt, $key, $model );
            if ( is_array( $resp ) && isset( $resp['rate_limited'] ) ) {
                continue;
            }
            if ( $resp ) {
                $this->log( 'ajax_test_model: success', array( 'provider' => 'gemini', 'model' => $model, 'key_prefix' => substr( $key, 0, 10 ) . '...' ) );
                wp_send_json_success( array( 'message' => 'Model accepted', 'model' => $model ) );
            }
        }

        $this->log( 'ajax_test_model: failed', array( 'provider' => 'gemini', 'model' => $model ) );
        wp_send_json_error( array( 'message' => 'All keys failed or are rate-limited' ) );
    }

    public function ajax_queue_translations() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        $post_ids = isset( $_POST['post_ids'] ) ? (array) $_POST['post_ids'] : array();
        $lang = sanitize_text_field( wp_unslash( $_POST['lang'] ?? '' ) );
        if ( empty( $post_ids ) || empty( $lang ) ) {
            wp_send_json_error( array( 'message' => 'Missing parameters' ) );
        }

        $queued = 0;
        foreach ( $post_ids as $post_id ) {
            $post_id = intval( $post_id );
            if ( $post_id <= 0 ) {
                continue;
            }
            if ( $this->queue_translation( $post_id, $lang, true ) ) {
                $queued++;
            }
        }

        $this->schedule_queue_runner();
        wp_send_json_success( array( 'message' => "Queued {$queued} item(s)." ) );
    }

    public function ajax_retranslate() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        $post_id = intval( $_POST['post_id'] ?? 0 );
        $lang = sanitize_text_field( wp_unslash( $_POST['lang'] ?? '' ) );
        if ( $post_id <= 0 || ! $lang ) {
            wp_send_json_error( array( 'message' => 'Missing parameters' ) );
        }

        $queued = $this->queue_translation( $post_id, $lang, true, true );
        $this->schedule_queue_runner();
        wp_send_json_success( array( 'message' => $queued ? 'Queued for re-translation' : 'No changes' ) );
    }

    public function ajax_get_statuses() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        $post_ids = isset( $_POST['post_ids'] ) ? (array) $_POST['post_ids'] : array();
        $post_ids = array_map( 'intval', $post_ids );
        if ( empty( $post_ids ) ) {
            wp_send_json_success( array( 'statuses' => array() ) );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $ids = implode( ',', array_map( 'intval', $post_ids ) );
        $rows = $wpdb->get_results( "SELECT * FROM {$table} WHERE source_post_id IN ({$ids})" );

        $map = array();
        foreach ( $rows as $row ) {
            $pid = intval( $row->source_post_id );
            if ( ! isset( $map[ $pid ] ) ) {
                $map[ $pid ] = array();
            }
            $source_modified = get_post_modified_time( 'U', true, $pid );
            $translated_modified = 0;
            if ( $row->translated_post_id ) {
                $translated_modified = get_post_modified_time( 'U', true, intval( $row->translated_post_id ) );
            }
            $translated_permalink = $row->translated_post_id ? get_permalink( intval( $row->translated_post_id ) ) : '';
            $last_trans = $row->last_translated;
            if ( ! $last_trans && $translated_modified ) {
                $last_trans = date( 'Y-m-d H:i:s', $translated_modified );
            }
            $translated_status = '';
            if ( $row->translated_post_id ) {
                $tp = get_post( intval( $row->translated_post_id ) );
                if ( $tp && isset( $tp->post_status ) ) {
                    $translated_status = $tp->post_status;
                }
            }

            // Compute freshness server-side using last_translated AND translated post modified time.
            $freshness = 'not_complete';
            if ( $row->status === 'completed' && $row->translated_post_id ) {
                $last_translated_ts = $last_trans ? strtotime( $last_trans ) : 0;
                $effective_translated = max( $last_translated_ts, $translated_modified );
                if ( $effective_translated && $source_modified && $effective_translated >= $source_modified ) {
                    $freshness = 'up_to_date';
                } else {
                    $freshness = 'out_of_date';
                }
            }

            $map[ $pid ][ $row->lang ] = array(
                'status' => $row->status,
                'last_translated' => $last_trans,
                'translated_post_id' => $row->translated_post_id ? intval( $row->translated_post_id ) : 0,
                'translated_post_status' => $translated_status,
                'translated_permalink' => $translated_permalink,
                'attempts' => intval( $row->attempts ),
                'next_retry' => $row->next_retry,
                'source_modified' => $source_modified,
                'translated_modified' => $translated_modified,
                'freshness' => $freshness,
            );
        }

        wp_send_json_success( array( 'statuses' => $map ) );
    }

    // Return counts per status and last run timestamp
    public function ajax_get_queue_summary() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $counts = $wpdb->get_results( "SELECT status, COUNT(*) as c FROM {$table} GROUP BY status" );
        $map = array();
        foreach ( $counts as $c ) {
            $map[ $c->status ] = intval( $c->c );
        }
        $last_run = get_option( 'rbt_last_run', '' );
        $next_scheduled = wp_next_scheduled( 'rbt_translator_process_queue' );
        $next_run = $next_scheduled ? date( 'Y-m-d H:i:s', $next_scheduled ) : 'Not scheduled';
        wp_send_json_success( array( 'summary' => $map, 'last_run' => $last_run, 'next_run' => $next_run ) );
    }

    // Return recent queue items (limit 200)
    public function ajax_get_queue_items() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        // Active/pending items plus the 20 most recently completed.
        $active   = $wpdb->get_results( "SELECT * FROM {$table} WHERE status IN ('processing','queued','failed','cancelled') ORDER BY FIELD(status,'processing','queued','failed','cancelled'), created_at DESC" );
        $completed = $wpdb->get_results( "SELECT * FROM {$table} WHERE status = 'completed' ORDER BY updated_at DESC LIMIT 20" );
        $rows = array_merge( $active ?: array(), $completed ?: array() );
        $items = array();
        foreach ( $rows as $r ) {
            $post = get_post( $r->source_post_id );
            $items[] = array(
                'id' => intval( $r->id ),
                'source_post_id' => intval( $r->source_post_id ),
                'title' => $post ? $post->post_title : '',
                'lang' => $r->lang,
                'status' => $r->status,
                'attempts' => intval( $r->attempts ),
                'next_retry' => $r->next_retry,
                'created_at' => $r->created_at,
                'updated_at' => $r->updated_at,
            );
        }
        wp_send_json_success( array( 'items' => $items ) );
    }

    public function ajax_cancel_translation() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $id = intval( $_POST['id'] ?? 0 );
        if ( ! $id ) wp_send_json_error( array( 'message' => 'Missing id' ) );
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $wpdb->update( $table, array( 'status' => 'cancelled' ), array( 'id' => $id ) );
        wp_send_json_success( array( 'message' => 'Cancelled' ) );
    }

    public function ajax_retry_translation() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $id = intval( $_POST['id'] ?? 0 );
        if ( ! $id ) wp_send_json_error( array( 'message' => 'Missing id' ) );
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $wpdb->update( $table, array( 'status' => 'queued', 'attempts' => 0, 'next_retry' => null ), array( 'id' => $id ) );
        $this->schedule_queue_runner();
        wp_send_json_success( array( 'message' => 'Re-queued' ) );
    }

    public function ajax_run_now() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $this->process_queue();
        $last_run = get_option( 'rbt_last_run', '' );
        wp_send_json_success( array( 'message' => 'Ran', 'last_run' => $last_run ) );
    }

    /**
     * Register public REST API routes.
     */
    public function register_rest_routes() {
        register_rest_route( 'rbt-translator/v1', '/translated-urls', array(
            'methods'             => 'GET',
            'callback'            => array( $this, 'rest_translated_urls' ),
            'permission_callback' => '__return_true',
            'args'                => array(
                'lang' => array(
                    'required'          => true,
                    'sanitize_callback' => 'sanitize_text_field',
                ),
            ),
        ) );
    }

    /**
     * REST handler: return { english_slug: translated_url } map for a language.
     * GET /wp-json/rbt-translator/v1/translated-urls?lang=ro
     */
    public function rest_translated_urls( $request ) {
        $lang = $request->get_param( 'lang' );
        if ( empty( $lang ) || $lang === 'en' ) {
            return new WP_REST_Response( array(), 200 );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows  = $wpdb->get_results( $wpdb->prepare(
            "SELECT source_post_id, translated_post_id FROM {$table} WHERE lang = %s AND status = 'completed' AND translated_post_id > 0",
            $lang
        ) );

        $map = array();
        foreach ( $rows as $row ) {
            $source = get_post( intval( $row->source_post_id ) );
            if ( ! $source ) continue;

            $translated = get_post( intval( $row->translated_post_id ) );
            if ( ! $translated || $translated->post_status !== 'publish' ) continue;

            $translated_url = get_permalink( $translated );
            if ( ! $translated_url || strpos( $translated_url, 'page_id=' ) !== false ) continue;

            // Key by English slug so React can match its hardcoded URLs
            $map[ $source->post_name ] = $translated_url;
        }

        // Cache for 10 minutes on the client
        return new WP_REST_Response( $map, 200, array(
            'Cache-Control' => 'public, max-age=600',
        ) );
    }

    public function ajax_fix_internal_links() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows = $wpdb->get_results( "SELECT translated_post_id, lang FROM {$table} WHERE status='completed' AND translated_post_id > 0" );
        $fixed = 0;
        foreach ( $rows as $row ) {
            $post = get_post( intval( $row->translated_post_id ) );
            if ( ! $post ) continue;
            $new_content = $this->replace_internal_links( $post->post_content, $row->lang );
            if ( $new_content !== $post->post_content ) {
                wp_update_post( array(
                    'ID'           => intval( $row->translated_post_id ),
                    'post_content' => $new_content,
                ) );
                $fixed++;
            }
        }
        $this->log( 'ajax_fix_internal_links: done', array( 'fixed' => $fixed ) );
        wp_send_json_success( array( 'message' => "Fixed internal links in {$fixed} translated post(s).", 'count' => $fixed ) );
    }

    public function ajax_requeue_out_of_date() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';

        // Get all source roots
        $source_query = new WP_Query( array(
            'post_type' => array( 'page', 'post' ),
            'posts_per_page' => -1,
            'post_status' => array( 'publish', 'draft', 'private' ),
            'meta_query' => array(
                array(
                    'key' => 'rbt_source_root',
                    'value' => '1',
                    'compare' => '=',
                )
            ),
        ) );

        $requeued = 0;
        foreach ( $source_query->posts as $source ) {
            $source_id = intval( $source->ID );
            $source_modified = get_post_modified_time( 'U', true, $source_id );
            if ( ! $source_modified ) {
                continue;
            }

            $rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} WHERE source_post_id=%d", $source_id ) );
            foreach ( $rows as $row ) {
                if ( $row->status !== 'completed' || empty( $row->translated_post_id ) ) {
                    continue;
                }
                $translated_id = intval( $row->translated_post_id );
                $translated_modified = get_post_modified_time( 'U', true, $translated_id );
                if ( ! $translated_modified ) {
                    continue;
                }
                // Consider the recorded last_translated timestamp (DB) as authoritative if present; otherwise use translated post modified time.
                $translated_time = 0;
                if ( ! empty( $row->last_translated ) ) {
                    $translated_time = strtotime( $row->last_translated );
                }
                if ( $translated_modified ) {
                    $translated_time = max( $translated_time, $translated_modified );
                }
                if ( $translated_time < $source_modified ) {
                    $wpdb->update(
                        $table,
                        array( 'status' => 'queued', 'attempts' => 0, 'next_retry' => null ),
                        array( 'id' => $row->id )
                    );
                    $requeued++;
                }
            }
        }

        if ( $requeued > 0 ) {
            $this->schedule_queue_runner();
        }

        wp_send_json_success( array( 'message' => "Re-queued {$requeued} out-of-date item(s).", 'count' => $requeued ) );
    }

    public function ajax_search_sources() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $q = sanitize_text_field( wp_unslash( $_POST['q'] ?? '' ) );
        if ( ! $q ) {
            wp_send_json_success( array( 'items' => array() ) );
        }

        $query = new WP_Query( array(
            'post_type' => array( 'page', 'post' ),
            'posts_per_page' => 10,
            'post_status' => array( 'publish', 'draft', 'private' ),
            's' => $q,
        ) );

        $items = array();
        foreach ( $query->posts as $p ) {
            $items[] = array(
                'id' => $p->ID,
                'title' => $p->post_title,
                'type' => $p->post_type,
                'status' => $p->post_status,
                'is_root' => get_post_meta( $p->ID, 'rbt_source_root', true ) === '1',
            );
        }

        wp_send_json_success( array( 'items' => $items ) );
    }

    public function ajax_add_source_root() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $post_id = intval( $_POST['post_id'] ?? 0 );
        if ( ! $post_id ) {
            wp_send_json_error( array( 'message' => 'Missing post_id' ) );
        }
        update_post_meta( $post_id, 'rbt_source_root', '1' );
        wp_send_json_success( array( 'message' => 'Added source' ) );
    }

    public function ajax_publish_translations() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        $post_id = intval( $_POST['post_id'] ?? 0 );
        if ( ! $post_id ) {
            wp_send_json_error( array( 'message' => 'Missing post_id' ) );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} WHERE source_post_id=%d AND translated_post_id IS NOT NULL", $post_id ) );

        $published = 0;
        foreach ( $rows as $row ) {
            $tid = intval( $row->translated_post_id );
            if ( ! $tid ) continue;
            $p = get_post( $tid );
            if ( ! $p ) continue;
            if ( $p->post_status !== 'publish' ) {
                wp_update_post( array( 'ID' => $tid, 'post_status' => 'publish' ) );
                $published++;
            }
        }

        wp_send_json_success( array( 'message' => "Published {$published} translation(s)", 'count' => $published ) );
    }

    /**
     * Publish ALL completed translations that are still in draft status.
     */
    public function ajax_publish_all_drafts() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows = $wpdb->get_results( "SELECT translated_post_id FROM {$table} WHERE status = 'completed' AND translated_post_id IS NOT NULL AND translated_post_id > 0" );

        $published = 0;
        foreach ( $rows as $row ) {
            $tid = intval( $row->translated_post_id );
            if ( ! $tid ) continue;
            $p = get_post( $tid );
            if ( ! $p || $p->post_status === 'publish' ) continue;
            wp_update_post( array( 'ID' => $tid, 'post_status' => 'publish' ) );
            $published++;
        }

        wp_send_json_success( array( 'message' => "Published {$published} draft translation(s)", 'count' => $published ) );
    }

    /**
     * Repair video/audio blocks in all translated posts.
     * Copies <video>/<audio>/<iframe> blocks from the source post into the translated post
     * where the translated version has an empty or stripped block.
     */
    public function ajax_repair_video() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows = $wpdb->get_results( "SELECT source_post_id, translated_post_id, lang FROM {$table} WHERE status = 'completed' AND translated_post_id IS NOT NULL AND translated_post_id > 0" );

        $repaired = 0;
        $details  = array();

        foreach ( $rows as $row ) {
            $source = get_post( intval( $row->source_post_id ) );
            $translated = get_post( intval( $row->translated_post_id ) );
            if ( ! $source || ! $translated ) continue;

            $src_content = $source->post_content;
            $tr_content  = $translated->post_content;

            // Extract video/audio/object blocks from source
            $tags_to_check = array( 'video', 'audio', 'object' );
            $changed = false;

            foreach ( $tags_to_check as $tag ) {
                // Find all instances of this tag in the source
                $src_blocks = $this->extract_tag_blocks( $src_content, $tag );
                if ( empty( $src_blocks ) ) continue;

                // Find instances in translation
                $tr_blocks = $this->extract_tag_blocks( $tr_content, $tag );

                // If translation has no blocks at all, append the source blocks
                if ( empty( $tr_blocks ) ) {
                    // Try to find a likely insertion point (end of content)
                    foreach ( $src_blocks as $block ) {
                        $tr_content .= "\n" . $block;
                        $changed = true;
                    }
                } else {
                    // Replace empty/stripped blocks with source versions
                    foreach ( $tr_blocks as $i => $tr_block ) {
                        // Check if block is empty (no <source> or no inner content)
                        $inner = preg_replace( '/<' . $tag . '[^>]*>/i', '', $tr_block );
                        $inner = preg_replace( '/<\/' . $tag . '>/i', '', $inner );
                        $inner = trim( strip_tags( $inner ) );

                        if ( empty( $inner ) && isset( $src_blocks[ $i ] ) ) {
                            $tr_content = str_replace( $tr_block, $src_blocks[ $i ], $tr_content );
                            $changed = true;
                        }
                    }
                }
            }

            if ( $changed ) {
                wp_update_post( array(
                    'ID'           => $translated->ID,
                    'post_content' => $tr_content,
                ) );
                $repaired++;
                $details[] = $row->lang . ' (post ' . $translated->ID . ')';
            }
        }

        wp_send_json_success( array(
            'message' => "Repaired video/media in {$repaired} translation(s)",
            'count'   => $repaired,
            'details' => $details,
        ) );
    }

    /**
     * Extract all occurrences of a specific HTML tag block from content.
     * Returns array of full tag strings including opening and closing tags.
     */
    private function extract_tag_blocks( $content, $tag ) {
        $blocks = array();
        $lower  = strtolower( $content );
        $open_tag = '<' . strtolower( $tag );
        $close_tag = '</' . strtolower( $tag ) . '>';
        $pos = 0;

        while ( ( $start = strpos( $lower, $open_tag, $pos ) ) !== false ) {
            $end = strpos( $lower, $close_tag, $start );
            if ( $end === false ) break;
            $end += strlen( $close_tag );
            $blocks[] = substr( $content, $start, $end - $start );
            $pos = $end;
        }

        return $blocks;
    }

    public function ajax_delete_translations() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        $post_id = intval( $_POST['post_id'] ?? 0 );
        if ( ! $post_id ) {
            wp_send_json_error( array( 'message' => 'Missing post_id' ) );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} WHERE source_post_id=%d", $post_id ) );

        $deleted_posts = 0;
        $deleted_rows = 0;

        foreach ( $rows as $row ) {
            // Delete the translated post if it exists
            $tid = intval( $row->translated_post_id );
            if ( $tid ) {
                // Determine if force delete or trash
                // wp_delete_post( $id, $force_delete ) -> if false, moves to trash
                // We'll trust trash first to be safe, but user said "delete all translations"
                // Let's force delete to clean up properly since they can re-generate easily.
                // Usually force delete helps keep WP clean if generated many times.
                // But let's use trash = false (trash it) to be slightly safer unless post type doesn't support trash.
                // Actually, for "re-do", trashing is fine.
                $result = wp_delete_post( $tid, true ); // true = bypass trash (force delete)
                if ( $result ) {
                    $deleted_posts++;
                }
            }
            // Remove the tracking row
            $wpdb->delete( $table, array( 'id' => $row->id ) );
            $deleted_rows++;
        }

        $this->log( 'ajax_delete_translations', array( 'source_id' => $post_id, 'deleted_posts' => $deleted_posts, 'deleted_rows' => $deleted_rows ) );
        wp_send_json_success( array( 
            'message' => "Deleted {$deleted_posts} translated post(s) and {$deleted_rows} tracking record(s).",
            'deleted_posts' => $deleted_posts,
            'deleted_rows' => $deleted_rows
        ) );
    }

    /**
     * Hook to publish translations when a source post is saved/published
     */
    public function on_source_saved( $post_id, $post, $update ) {
        // Only act for post/page types and when auto-publish is enabled
        if ( ! in_array( $post->post_type, array( 'post', 'page' ), true ) ) return;

        $settings = $this->get_settings();
        if ( empty( $settings['auto_publish_on_source_publish'] ) ) return;

        // Avoid running on translated posts (they have rbt_source_id meta)
        if ( get_post_meta( $post_id, 'rbt_source_id', true ) ) return;

        // Only proceed when the source is published
        if ( $post->post_status !== 'publish' ) return;

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} WHERE source_post_id=%d AND translated_post_id IS NOT NULL", $post_id ) );

        foreach ( $rows as $row ) {
            $tid = intval( $row->translated_post_id );
            if ( ! $tid ) continue;
            $p = get_post( $tid );
            if ( ! $p ) continue;
            if ( $p->post_status !== 'publish' ) {
                wp_update_post( array( 'ID' => $tid, 'post_status' => 'publish' ) );
            }
        }
    }

    public function ajax_remove_source_root() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'edit_posts' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $post_id = intval( $_POST['post_id'] ?? 0 );
        if ( ! $post_id ) {
            wp_send_json_error( array( 'message' => 'Missing post_id' ) );
        }
        delete_post_meta( $post_id, 'rbt_source_root' );
        wp_send_json_success( array( 'message' => 'Removed source' ) );
    }

    public function ajax_get_log() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        $log = get_option( 'rbt_translator_log', array() );
        // Reverse so newest first
        $log = array_reverse( $log );
        wp_send_json_success( array( 'log' => $log ) );
    }

    public function ajax_clear_log() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }
        update_option( 'rbt_translator_log', array() );
        wp_send_json_success( array( 'message' => 'Log cleared' ) );
    }

    /**
     * Clear completed queue entries (removes rows with status = 'completed')
     */
    public function ajax_clear_completed() {
        check_ajax_referer( 'rbt_translator_nonce', 'nonce' );
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => 'Unauthorized' ) );
        }

        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        // Delete completed rows that have no translated post attached; keep real translations for tracking
        $deleted = $wpdb->query( $wpdb->prepare( "DELETE FROM {$table} WHERE status=%s AND (translated_post_id IS NULL OR translated_post_id=0)", 'completed' ) );
        if ( $deleted === false ) {
            wp_send_json_error( array( 'message' => 'Failed to clear completed items' ) );
        }

        $this->log( 'ajax_clear_completed', array( 'deleted' => $deleted ) );
        wp_send_json_success( array( 'message' => "Cleared {$deleted} completed item(s)", 'count' => intval( $deleted ) ) );
    }

    private function queue_translation( $post_id, $lang, $force = false, $retranslate = false ) {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE source_post_id=%d AND lang=%s", $post_id, $lang ) );

        if ( $row ) {
            if ( $force || $retranslate ) {
                $wpdb->update(
                    $table,
                    array( 'status' => 'queued', 'attempts' => 0, 'next_retry' => null ),
                    array( 'id' => $row->id )
                );
                return true;
            }
            return false;
        }

        $wpdb->insert(
            $table,
            array(
                'source_post_id' => $post_id,
                'lang' => $lang,
                'status' => 'queued',
                'attempts' => 0,
                'next_retry' => null
            )
        );
        return true;
    }

    /**
     * Extract non-translatable HTML blocks (video, iframe, etc.) and replace with placeholders.
     * Uses string-based (non-regex) tag search to avoid PCRE backtracking failures on large content.
     * Returns array( 'content' => $modified_content, 'blocks' => array( placeholder => original_html ) ).
     */
    private function extract_protected_blocks( $content ) {
        $blocks = array();
        $idx    = 0;

        // Tags whose full open→close block must be shielded from the AI.
        $tags = array( 'video', 'iframe', 'object', 'script', 'pre' );

        foreach ( $tags as $tag ) {
            $open  = '<' . $tag;          // e.g. '<video'
            $close = '</' . $tag . '>';   // e.g. '</video>'
            $result = '';
            $pos   = 0;
            $len   = strlen( $content );

            while ( $pos < $len ) {
                $start = stripos( $content, $open, $pos );
                if ( $start === false ) {
                    $result .= substr( $content, $pos );
                    break;
                }

                // Verify this is a real tag and not e.g. <videos> or <preview>
                $after = isset( $content[ $start + strlen( $open ) ] ) ? $content[ $start + strlen( $open ) ] : '';
                if ( $after !== '' && $after !== '>' && $after !== ' ' && $after !== "\t" && $after !== "\n" && $after !== "\r" && $after !== '/' ) {
                    // Not a real opening tag — copy up-to-and-including the char and move on
                    $result .= substr( $content, $pos, $start - $pos + strlen( $open ) + 1 );
                    $pos = $start + strlen( $open ) + 1;
                    continue;
                }

                $end = stripos( $content, $close, $start );
                if ( $end === false ) {
                    // Unclosed tag — leave rest of content as-is
                    $result .= substr( $content, $pos );
                    break;
                }
                $end += strlen( $close );

                // Append content before block, then substitute placeholder
                $result .= substr( $content, $pos, $start - $pos );
                $block       = substr( $content, $start, $end - $start );
                $placeholder = 'RBTPROTECTED' . $idx . 'ENDPROTECTED';
                $blocks[ $placeholder ] = $block;
                $idx++;
                $result .= $placeholder;
                $pos = $end;
            }

            $content = $result;
        }

        return array( 'content' => $content, 'blocks' => $blocks );
    }

    /**
     * Restore protected blocks by replacing placeholders with the original HTML.
     * Also handles cases where Gemini adds surrounding whitespace to the placeholder.
     */
    private function restore_protected_blocks( $content, $blocks ) {
        if ( empty( $blocks ) ) return $content;
        foreach ( $blocks as $placeholder => $original ) {
            // Exact match first
            if ( strpos( $content, $placeholder ) !== false ) {
                $content = str_replace( $placeholder, $original, $content );
            } else {
                // Fuzzy: Gemini may have wrapped placeholder in spaces or put it on its own line
                $fuzzy = '/' . preg_quote( $placeholder, '/' ) . '/i';
                $content = preg_replace( $fuzzy, $original, $content );
            }
        }
        return $content;
    }

    /**
     * Scan translated content for internal English-slug links and replace them with
     * the translated post URL when a completed translation exists for the given language.
     */
    private function replace_internal_links( $content, $lang ) {
        $host = wp_parse_url( home_url(), PHP_URL_HOST );
        if ( ! $host ) return $content;

        $skip_paths = array(
            'wp-content', 'wp-includes', 'wp-admin', 'wp-login.php',
            'feed', 'sitemap', 'go', 'search', 'tag', 'category', 'author',
        );

        return preg_replace_callback(
            '/https?:\/\/' . preg_quote( $host, '/' ) . '\/([a-z0-9][a-zA-Z0-9_-]*)\/(?=["\' \t\n>])/i',
            function ( $m ) use ( $lang, $skip_paths ) {
                $slug = $m[1];
                if ( in_array( $slug, $skip_paths, true ) ) {
                    return $m[0];
                }
                $post = get_page_by_path( $slug, OBJECT, array( 'post', 'page' ) );
                if ( ! $post ) return $m[0];

                global $wpdb;
                $table = $wpdb->prefix . 'rbt_translations';
                $row = $wpdb->get_row( $wpdb->prepare(
                    "SELECT translated_post_id FROM {$table} WHERE source_post_id=%d AND lang=%s AND status='completed' AND translated_post_id > 0 LIMIT 1",
                    intval( $post->ID ), $lang
                ) );
                if ( ! $row || ! $row->translated_post_id ) return $m[0];

                $url = get_permalink( intval( $row->translated_post_id ) );
                return $url ? trailingslashit( $url ) : $m[0];
            },
            $content
        );
    }

    private function schedule_queue_runner() {
        if ( ! wp_next_scheduled( 'rbt_translator_process_queue' ) ) {
            global $wpdb;
            $table = $wpdb->prefix . 'rbt_translations';

            // If there are queued items with a future next_retry, schedule at the earliest next_retry.
            $row = $wpdb->get_row( "SELECT MIN(next_retry) AS next_retry FROM {$table} WHERE status='queued' AND next_retry IS NOT NULL" );
            if ( $row && ! empty( $row->next_retry ) ) {
                $next_ts = strtotime( $row->next_retry );
                $now = current_time( 'timestamp' );
                // Only schedule in the future; otherwise schedule shortly
                if ( $next_ts > $now ) {
                    wp_schedule_single_event( $next_ts, 'rbt_translator_process_queue' );
                    return;
                }
            }

            // Default: schedule soon
            wp_schedule_single_event( time() + 30, 'rbt_translator_process_queue' );
        }
    }

    public function process_queue() {
        global $wpdb;
        $settings = $this->get_settings();
        $table = $wpdb->prefix . 'rbt_translations';

        $batch_size = max( 1, min( 10, intval( $settings['batch_size'] ) ) );
        // Update last run timestamp
        update_option( 'rbt_last_run', current_time( 'mysql' ) );

        // Use WordPress timezone-aware 'now' value to compare with next_retry to avoid DB-server timezone skew
        $now_mysql = date( 'Y-m-d H:i:s', current_time( 'timestamp' ) );
        $this->log( 'process_queue started', array( 'now_mysql' => $now_mysql, 'batch_size' => $batch_size ) );

        // Rescue items stuck in 'processing' for over 10 minutes (e.g., after server crash or timeout).
        $stuck_timeout = date( 'Y-m-d H:i:s', current_time( 'timestamp' ) - 600 );
        $stuck_count = $wpdb->query( $wpdb->prepare(
            "UPDATE {$table} SET status='queued', next_retry=NULL WHERE status='processing' AND updated_at <= %s",
            $stuck_timeout
        ) );
        if ( $stuck_count ) {
            $this->log( 'process_queue: rescued stuck-processing items', array( 'count' => $stuck_count ) );
        }

        // Poll any pending OpenAI batches first
        $this->poll_openai_batches( $settings );

        $rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} WHERE status=%s AND (next_retry IS NULL OR next_retry <= %s) ORDER BY updated_at ASC LIMIT %d", 'queued', $now_mysql, $batch_size ) );
        if ( empty( $rows ) ) {
            // Check if there are any queued items with future next_retry
            $future_count = $wpdb->get_var( $wpdb->prepare( "SELECT COUNT(*) FROM {$table} WHERE status=%s AND next_retry > %s", 'queued', $now_mysql ) );
            $this->log( 'process_queue: no rows ready', array( 'future_queued_count' => $future_count ) );
            // Ensure future next_retry is scheduled
            $this->schedule_queue_runner();
            return;
        }

        $this->log( 'process_queue: processing rows', array( 'count' => count( $rows ), 'ids' => array_map( function( $r ) { return $r->id; }, $rows ) ) );

        // If OpenAI provider with batch mode enabled, submit batch instead of per-row processing
        if ( isset( $settings['model_provider'] ) && $settings['model_provider'] === 'openai' && ! empty( $settings['openai_batch_mode'] ) ) {
            $this->submit_openai_batch( $rows, $settings );
        } else {
            foreach ( $rows as $row ) {
                $wpdb->update( $table, array( 'status' => 'processing' ), array( 'id' => $row->id ) );
                $this->translate_row( $row, $settings );
            }
        }

        $this->schedule_queue_runner();
    }

    private function translate_row( $row, $settings ) {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';

        $this->log( 'translate_row: starting', array( 'id' => $row->id, 'source_post_id' => $row->source_post_id, 'lang' => $row->lang, 'attempts' => $row->attempts ) );

        $source = get_post( $row->source_post_id );
        if ( ! $source ) {
            $this->log( 'translate_row: source post not found', array( 'id' => $row->id, 'source_post_id' => $row->source_post_id ) );
            $wpdb->update( $table, array( 'status' => 'failed' ), array( 'id' => $row->id ) );
            return;
        }

        $translated = $this->translate_html( $source->post_title, $source->post_content, $row->lang, $settings );
        if ( ! $translated ) {
            // Exponential backoff: increase attempts and schedule next retry
            $attempts = intval( $row->attempts ) + 1;
            $max_attempts = 5;
            $minutes = min( 60, pow( 2, $attempts ) ); // 2,4,8,16,32 minutes, capped at 60
            // Use WordPress timezone-aware timestamp for next_retry to avoid DB vs PHP timezone skew
            $next_retry = date( 'Y-m-d H:i:s', current_time( 'timestamp' ) + ( $minutes * 60 ) );

            if ( $attempts <= $max_attempts ) {
                $this->log( 'translate_row: API failed, retry scheduled', array( 'id' => $row->id, 'attempts' => $attempts, 'next_retry' => $next_retry ) );
                $wpdb->update( $table, array( 'attempts' => $attempts, 'next_retry' => $next_retry, 'status' => 'queued' ), array( 'id' => $row->id ) );
            } else {
                $this->log( 'translate_row: API failed, max attempts reached', array( 'id' => $row->id, 'attempts' => $attempts ) );
                $wpdb->update( $table, array( 'attempts' => $attempts, 'status' => 'failed' ), array( 'id' => $row->id ) );
            }
            return;
        }

        // Handle rate-limited response (all keys exhausted)
        if ( is_array( $translated ) && isset( $translated['rate_limited'] ) ) {
            $retry_seconds = max( 60, intval( $translated['retry_seconds'] ) ); // At least 60s
            $next_retry = date( 'Y-m-d H:i:s', current_time( 'timestamp' ) + $retry_seconds );
            $this->log( 'translate_row: rate limited, short retry scheduled', array( 'id' => $row->id, 'retry_seconds' => $retry_seconds, 'next_retry' => $next_retry ) );
            $wpdb->update( $table, array( 'next_retry' => $next_retry, 'status' => 'queued' ), array( 'id' => $row->id ) );
            return;
        }

        $this->log( 'translate_row: translation successful', array( 'id' => $row->id ) );

        $status = $settings['target_status'] === 'publish' ? 'publish' : 'draft';
        $translated_post_id = $row->translated_post_id ? intval( $row->translated_post_id ) : 0;

        // Determine safe source values (some environments may return unexpected types)
        $source_id = intval( $row->source_post_id );
        $source_obj = is_object( $source ) ? $source : null;
        $source_post_type = $source_obj ? $source_obj->post_type : get_post_field( 'post_type', $source_id );
        $source_post_name = $source_obj ? $source_obj->post_name : get_post_field( 'post_name', $source_id );

        // Generate a URL-safe slug from the translated title
        $new_slug = isset( $translated['title'] ) ? sanitize_title( $translated['title'] ) : '';

        // Replace English-slug internal links with translated equivalents.
        if ( ! empty( $translated['content'] ) ) {
            $translated['content'] = $this->replace_internal_links( $translated['content'], $row->lang );
        }

        if ( $translated_post_id ) {
            wp_update_post( array(
                'ID' => $translated_post_id,
                'post_title' => $translated['title'],
                'post_content' => $translated['content'],
                'post_status' => $status,
                'post_name' => $new_slug,
            ) );
        } else {
            $translated_post_id = wp_insert_post( array(
                'post_type' => $source_post_type ?: 'post',
                'post_title' => $translated['title'],
                'post_content' => $translated['content'],
                'post_status' => $status,
                'post_name' => $new_slug,
                'post_parent' => $source_post_type === 'page' ? 0 : 0,
            ) );
        }

        if ( $translated_post_id ) {
            update_post_meta( $translated_post_id, 'rbt_lang', $row->lang );
            update_post_meta( $translated_post_id, 'rbt_source_id', $source_id );
            update_post_meta( $translated_post_id, 'rbt_source_slug', $source_post_name );
            update_post_meta( $translated_post_id, 'rbt_source_type', $source_post_type );
        }

        $wpdb->update(
            $table,
            array(
                'status' => 'completed',
                'translated_post_id' => $translated_post_id,
                'last_translated' => current_time( 'mysql' ),
            ),
            array( 'id' => $row->id )
        );
    }

    private function translate_html( $title, $content, $lang, $settings ) {
        $provider = isset( $settings['model_provider'] ) ? $settings['model_provider'] : 'gemini';
        $provider = in_array( $provider, array( 'gemini', 'openai' ), true ) ? $provider : 'gemini';

        if ( $provider === 'openai' ) {
            $openai_key = isset( $settings['openai_api_key'] ) ? $settings['openai_api_key'] : '';
            $openai_model = isset( $settings['openai_model'] ) ? $settings['openai_model'] : 'gpt-4.1-mini';
            if ( empty( $openai_key ) ) {
                $this->log( 'translate_html: no OpenAI API key configured', array() );
                return null;
            }

            $this->log( 'translate_html: starting', array( 'lang' => $lang, 'provider' => 'openai', 'model' => $openai_model ) );
        } else {
            $keys = array_filter( array_map( 'trim', explode( ',', $settings['gemini_keys'] ) ) );
            if ( empty( $keys ) ) {
                $this->log( 'translate_html: no Gemini API keys configured', array() );
                return null;
            }

            $this->log( 'translate_html: starting', array( 'lang' => $lang, 'provider' => 'gemini', 'model' => ( isset( $settings['gemini_model'] ) ? $settings['gemini_model'] : '' ), 'keys_count' => count( $keys ), 'key_prefixes' => array_map( function( $k ) { return substr( $k, 0, 10 ) . '...'; }, $keys ) ) );

            // Check key availability up front
            $available_keys = array_filter( $keys, function( $k ) { return $this->key_is_available( $k ); } );
            $min_next = 0;
            if ( empty( $available_keys ) ) {
                // No keys currently available: return rate-limited minimum next available seconds
                $min_next = $this->get_min_key_next_seconds( $keys );
                if ( $min_next <= 0 ) $min_next = 60; // fallback
                $this->log( 'translate_html: all keys busy, min_next_secs', array( 'min_next' => $min_next ) );
                return array( 'rate_limited' => true, 'retry_seconds' => $min_next );
            }
        }

        // Protect non-translatable HTML blocks (video, iframe, etc.) before sending to AI.
        $prot = $this->extract_protected_blocks( $content );
        $content = $prot['content'];
        $this->log( 'translate_html: extraction', array(
            'blocks_extracted' => count( $prot['blocks'] ),
            'placeholders'     => array_keys( $prot['blocks'] ),
            'video_still_in_content' => ( stripos( $content, '<video' ) !== false ),
        ) );

        $prompt = "Translate the following WordPress content to language code '{$lang}'.\n\n";
        $prompt .= "Instructions:\n";
        $prompt .= "- Preserve ALL HTML tags and attributes exactly.\n";
        $prompt .= "- Preserve shortcodes like [shortcode] or [gallery] exactly.\n";
        $prompt .= "- Do NOT translate or modify tokens like RBTPROTECTED0ENDPROTECTED, RBTPROTECTED1ENDPROTECTED, etc. Output each one verbatim exactly as written.\n";
        $prompt .= "- Translate only human-readable text.\n\n";
        
        // For very large content, prefer chunking when using Gemini to avoid single huge requests.
        $prompt_tail = "TITLE:\n{$title}\n\nCONTENT:\n" . $content;
        $max_chars = 30000;

        if ( $provider !== 'openai' && strlen( $prompt ) + strlen( $prompt_tail ) > $max_chars ) {
            $this->log( 'translate_html: content too large, splitting into chunks', array( 'content_length' => strlen( $content ), 'max_chars' => $max_chars ) );
            $chunks = $this->chunk_html_by_size( $content, $max_chars );

            $translated_parts = array();
            $translated_title = '';
            $min_retry_seconds = 0;
            foreach ( $chunks as $idx => $chunk ) {
                $chunk_prompt = $prompt . "TITLE:\n{$title}\n\nCONTENT:\n" . $chunk;
                $translated_chunk = null;

                foreach ( $keys as $key ) {
                    $resp = $this->call_gemini( $chunk_prompt, $key );
                    if ( is_array( $resp ) && isset( $resp['rate_limited'] ) ) {
                        $min_retry_seconds = max( $min_retry_seconds, $resp['retry_seconds'] );
                        continue;
                    }
                    if ( $resp ) {
                        $parts = explode( 'CONTENT:', $resp, 2 );

                        // Capture translated title once (typically present before CONTENT:)
                        if ( empty( $translated_title ) ) {
                            $raw_title_part = trim( $parts[0] ?? '' );
                            $maybe_title = trim( str_replace( 'TITLE:', '', $raw_title_part ) );
                            if ( ! empty( $maybe_title ) ) {
                                $translated_title = $maybe_title;
                            }
                        }

                        $translated_chunk = trim( $parts[1] ?? '' );
                        break;
                    }
                }

                if ( $translated_chunk === null ) {
                    return array( 'rate_limited' => true, 'retry_seconds' => max( 60, $min_retry_seconds ) );
                }
                $translated_parts[] = $translated_chunk;
            }

            if ( empty( $translated_title ) ) {
                $translated_title = $title;
            }

            $merged = implode( "\n\n", $translated_parts );
            // Sanitize first, THEN restore protected blocks so wp_kses_post doesn't strip video/iframe.
            $merged = $this->restore_protected_blocks( wp_kses_post( $merged ), $prot['blocks'] );
            return array(
                'title' => sanitize_text_field( $translated_title ),
                'content' => $merged
            );
        }

        // Default (non-chunked) prompt used below
        $prompt .= "TITLE:\n{$title}\n\nCONTENT:\n{$content}";

        $min_retry_seconds = 0;
        if ( $provider === 'openai' ) {
            $resp = $this->call_openai( $prompt, $openai_key, $openai_model );
            if ( is_array( $resp ) && isset( $resp['rate_limited'] ) ) {
                return array( 'rate_limited' => true, 'retry_seconds' => $resp['retry_seconds'] );
            }
            if ( $resp ) {
                $parts = explode( 'CONTENT:', $resp, 2 );
                $new_title = trim( str_replace( 'TITLE:', '', $parts[0] ?? '' ) );
                $new_content = trim( $parts[1] ?? '' );
                // Sanitize first, THEN restore protected blocks so wp_kses_post doesn't strip video/iframe.
                $new_content = $this->restore_protected_blocks( wp_kses_post( $new_content ), $prot['blocks'] );

                return array(
                    'title' => sanitize_text_field( $new_title ),
                    'content' => $new_content
                );
            }
            return null;
        }

        foreach ( $keys as $key ) {
            $resp = $this->call_gemini( $prompt, $key );
            // Handle rate limit response
            if ( is_array( $resp ) && isset( $resp['rate_limited'] ) ) {
                $min_retry_seconds = max( $min_retry_seconds, $resp['retry_seconds'] );
                continue; // Try next key
            }
            if ( $resp ) {
                $parts = explode( 'CONTENT:', $resp, 2 );
                $new_title = trim( str_replace( 'TITLE:', '', $parts[0] ?? '' ) );
                $new_content = trim( $parts[1] ?? '' );
                // Sanitize first, THEN restore protected blocks so wp_kses_post doesn't strip video/iframe.
                $new_content = $this->restore_protected_blocks( wp_kses_post( $new_content ), $prot['blocks'] );

                return array(
                    'title' => sanitize_text_field( $new_title ),
                    'content' => $new_content
                );
            }
        }

        // If all keys are rate limited, return the minimum retry time
        if ( $min_retry_seconds > 0 ) {
            return array( 'rate_limited' => true, 'retry_seconds' => $min_retry_seconds );
        }

        return null;
    }

    private function submit_openai_batch( $rows, $settings ) {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $batch_table = $wpdb->prefix . 'rbt_openai_batches';

        $openai_key = isset( $settings['openai_api_key'] ) ? $settings['openai_api_key'] : '';
        $openai_model = isset( $settings['openai_model'] ) ? $settings['openai_model'] : 'gpt-4.1-mini';
        $batch_size = max( 1, min( 200, intval( $settings['openai_batch_size'] ?? 20 ) ) );
        $window = isset( $settings['openai_batch_window'] ) ? $settings['openai_batch_window'] : '24h';

        if ( empty( $openai_key ) ) {
            $this->log( 'submit_openai_batch: missing OpenAI key', array() );
            return;
        }

        $rows = array_slice( $rows, 0, $batch_size );
        if ( empty( $rows ) ) return;

        $upload_dir = wp_upload_dir();
        $batch_dir = trailingslashit( $upload_dir['basedir'] ) . 'rbt-batches';
        if ( ! file_exists( $batch_dir ) ) {
            wp_mkdir_p( $batch_dir );
        }

        $file_path = $batch_dir . '/batch_' . time() . '_' . wp_generate_password( 6, false ) . '.jsonl';
        $fh = fopen( $file_path, 'w' );
        if ( ! $fh ) {
            $this->log( 'submit_openai_batch: failed to open file', array( 'path' => $file_path ) );
            return;
        }

        $ids = array();
        foreach ( $rows as $row ) {
            $source = get_post( $row->source_post_id );
            if ( ! $source ) continue;
            $prompt = "Translate the following WordPress content to language code '{$row->lang}'.\n\n";
            $prompt .= "Instructions:\n";
            $prompt .= "- Preserve ALL HTML tags and attributes exactly.\n";
            $prompt .= "- Preserve shortcodes like [shortcode] or [gallery] exactly.\n";
            $prompt .= "- Translate only human-readable text.\n\n";
            $prompt .= "TITLE:\n{$source->post_title}\n\nCONTENT:\n{$source->post_content}";

            $line = array(
                'custom_id' => 'rbt_' . $row->id,
                'method' => 'POST',
                'url' => '/v1/chat/completions',
                'body' => array(
                    'model' => $openai_model,
                    'messages' => array(
                        array( 'role' => 'system', 'content' => 'You are a translation engine. Preserve all HTML tags and shortcodes exactly. Only translate human-readable text.' ),
                        array( 'role' => 'user', 'content' => $prompt ),
                    ),
                    'temperature' => 0.1,
                )
            );

            fwrite( $fh, wp_json_encode( $line ) . "\n" );
            $ids[] = intval( $row->id );
        }
        fclose( $fh );

        if ( empty( $ids ) ) {
            $this->log( 'submit_openai_batch: no valid rows', array() );
            return;
        }

        // Upload batch file
        $file_id = $this->openai_upload_file( $file_path, $openai_key );
        if ( ! $file_id ) {
            $this->log( 'submit_openai_batch: file upload failed', array() );
            return;
        }

        // Create batch
        $batch_id = $this->openai_create_batch( $file_id, $openai_key, $window );
        if ( ! $batch_id ) {
            $this->log( 'submit_openai_batch: create batch failed', array( 'file_id' => $file_id ) );
            return;
        }

        // Mark rows as processing
        foreach ( $ids as $id ) {
            $wpdb->update( $table, array( 'status' => 'processing' ), array( 'id' => $id ) );
        }

        $wpdb->insert( $batch_table, array(
            'batch_id' => $batch_id,
            'status' => 'submitted',
            'items_json' => wp_json_encode( $ids ),
        ) );

        $this->log( 'submit_openai_batch: submitted', array( 'batch_id' => $batch_id, 'count' => count( $ids ) ) );
    }

    private function poll_openai_batches( $settings ) {
        if ( ! isset( $settings['model_provider'] ) || $settings['model_provider'] !== 'openai' ) {
            return;
        }
        $openai_key = isset( $settings['openai_api_key'] ) ? $settings['openai_api_key'] : '';
        if ( empty( $openai_key ) ) return;

        global $wpdb;
        $batch_table = $wpdb->prefix . 'rbt_openai_batches';
        $rows = $wpdb->get_results( "SELECT * FROM {$batch_table} WHERE status NOT IN ('completed','failed') ORDER BY created_at ASC LIMIT 10" );
        if ( empty( $rows ) ) return;

        foreach ( $rows as $b ) {
            $batch = $this->openai_get_batch( $b->batch_id, $openai_key );
            if ( ! $batch ) continue;
            $status = $batch['status'] ?? $b->status;
            $output_file_id = $batch['output_file_id'] ?? null;

            if ( $status === 'completed' && $output_file_id ) {
                $content = $this->openai_download_file( $output_file_id, $openai_key );
                if ( $content ) {
                    $this->process_openai_batch_results( $content, $settings );
                    $wpdb->update( $batch_table, array( 'status' => 'completed', 'output_file_id' => $output_file_id ), array( 'id' => $b->id ) );
                    $this->log( 'openai_batch: completed', array( 'batch_id' => $b->batch_id ) );
                }
            } elseif ( in_array( $status, array( 'failed', 'expired', 'canceled' ), true ) ) {
                $wpdb->update( $batch_table, array( 'status' => 'failed', 'error' => wp_json_encode( $batch ) ), array( 'id' => $b->id ) );
                $this->log( 'openai_batch: failed', array( 'batch_id' => $b->batch_id, 'status' => $status ) );
            } else {
                $wpdb->update( $batch_table, array( 'status' => $status ), array( 'id' => $b->id ) );
            }
        }
    }

    private function process_openai_batch_results( $content, $settings ) {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $lines = preg_split( '/\r\n|\r|\n/', trim( $content ) );
        foreach ( $lines as $line ) {
            if ( ! $line ) continue;
            $obj = json_decode( $line, true );
            if ( ! $obj || empty( $obj['custom_id'] ) ) continue;
            if ( ! preg_match( '/rbt_(\d+)/', $obj['custom_id'], $m ) ) continue;
            $id = intval( $m[1] );

            $row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id=%d", $id ) );
            if ( ! $row ) continue;

            $resp = $obj['response'] ?? null;
            if ( ! $resp || empty( $resp['body']['choices'][0]['message']['content'] ) || intval( $resp['status_code'] ?? 0 ) !== 200 ) {
                $wpdb->update( $table, array( 'status' => 'failed' ), array( 'id' => $id ) );
                continue;
            }

            $text = $resp['body']['choices'][0]['message']['content'];
            $parts = explode( 'CONTENT:', $text, 2 );
            $new_title = trim( str_replace( 'TITLE:', '', $parts[0] ?? '' ) );
            $new_content = trim( $parts[1] ?? '' );

            // Protect video/iframe blocks from wp_kses_post stripping.
            $prot = $this->extract_protected_blocks( $new_content );
            $new_content = $this->restore_protected_blocks( wp_kses_post( $prot['content'] ), $prot['blocks'] );

            $this->apply_translation_result( $row, array( 'title' => sanitize_text_field( $new_title ), 'content' => $new_content ), $settings );
        }
    }

    private function apply_translation_result( $row, $translated, $settings ) {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';

        $status = $settings['target_status'] === 'publish' ? 'publish' : 'draft';
        $translated_post_id = $row->translated_post_id ? intval( $row->translated_post_id ) : 0;

        $source = get_post( $row->source_post_id );
        $source_id = intval( $row->source_post_id );
        $source_obj = is_object( $source ) ? $source : null;
        $source_post_type = $source_obj ? $source_obj->post_type : get_post_field( 'post_type', $source_id );
        $source_post_name = $source_obj ? $source_obj->post_name : get_post_field( 'post_name', $source_id );

        // Generate a URL-safe slug from the translated title
        $new_slug = isset( $translated['title'] ) ? sanitize_title( $translated['title'] ) : '';

        // Replace English-slug internal links with translated equivalents.
        if ( ! empty( $translated['content'] ) ) {
            $translated['content'] = $this->replace_internal_links( $translated['content'], $row->lang );
        }

        if ( $translated_post_id ) {
            wp_update_post( array(
                'ID' => $translated_post_id,
                'post_title' => $translated['title'],
                'post_content' => $translated['content'],
                'post_status' => $status,
                'post_name' => $new_slug,
            ) );
        } else {
            $translated_post_id = wp_insert_post( array(
                'post_type' => $source_post_type ?: 'post',
                'post_title' => $translated['title'],
                'post_content' => $translated['content'],
                'post_status' => $status,
                'post_name' => $new_slug,
                'post_parent' => $source_post_type === 'page' ? 0 : 0,
            ) );
        }

        if ( $translated_post_id ) {
            update_post_meta( $translated_post_id, 'rbt_lang', $row->lang );
            update_post_meta( $translated_post_id, 'rbt_source_id', $source_id );
            update_post_meta( $translated_post_id, 'rbt_source_slug', $source_post_name );
            update_post_meta( $translated_post_id, 'rbt_source_type', $source_post_type );
        }

        $wpdb->update(
            $table,
            array(
                'status' => 'completed',
                'translated_post_id' => $translated_post_id,
                'last_translated' => current_time( 'mysql' ),
            ),
            array( 'id' => $row->id )
        );
    }

    private function openai_upload_file( $file_path, $api_key ) {
        if ( ! file_exists( $file_path ) ) {
            $this->log( 'openai_upload_file: file missing', array( 'path' => $file_path ) );
            return null;
        }
        if ( ! is_readable( $file_path ) ) {
            $this->log( 'openai_upload_file: file not readable', array( 'path' => $file_path ) );
            return null;
        }
        $file_size = filesize( $file_path );
        $this->log( 'openai_upload_file: preparing', array( 'path' => $file_path, 'size' => $file_size ) );
        $url = 'https://api.openai.com/v1/files';
        $body = array(
            'purpose' => 'batch',
        );

        // Prefer cURL for multipart upload to avoid WP adding file[name]/file[mime] fields.
        if ( function_exists( 'curl_init' ) && class_exists( 'CURLFile' ) ) {
            $body['file'] = new CURLFile( $file_path, 'application/jsonl', basename( $file_path ) );
            $ch = curl_init( $url );
            curl_setopt( $ch, CURLOPT_POST, true );
            curl_setopt( $ch, CURLOPT_POSTFIELDS, $body );
            curl_setopt( $ch, CURLOPT_HTTPHEADER, array(
                'Authorization: Bearer ' . $api_key,
                'Accept: application/json',
            ) );
            curl_setopt( $ch, CURLOPT_RETURNTRANSFER, true );
            curl_setopt( $ch, CURLOPT_TIMEOUT, 120 );
            $response_body = curl_exec( $ch );
            $curl_err = curl_error( $ch );
            $response_code = curl_getinfo( $ch, CURLINFO_HTTP_CODE );
            curl_close( $ch );

            if ( $curl_err ) {
                $this->log( 'openai_upload_file: curl error', array( 'error' => $curl_err ) );
                return null;
            }
            if ( $response_code !== 200 ) {
                $this->log( 'openai_upload_file: HTTP error', array( 'code' => $response_code, 'body' => substr( $response_body, 0, 800 ) ) );
                return null;
            }
            $data = json_decode( $response_body, true );
            if ( empty( $data['id'] ) ) {
                $this->log( 'openai_upload_file: missing file id', array( 'body' => substr( $response_body, 0, 800 ) ) );
                return null;
            }
            return $data['id'];
        }

        // Fallback to WP HTTP API if cURL is not available.
        if ( class_exists( 'CURLFile' ) ) {
            $body['file'] = new CURLFile( $file_path, 'application/jsonl', basename( $file_path ) );
        } else {
            $body['file'] = '@' . $file_path;
        }

        $resp = wp_remote_post( $url, array(
            'headers' => array(
                'Authorization' => 'Bearer ' . $api_key,
                'Accept' => 'application/json',
            ),
            'body' => $body,
            'timeout' => 120,
        ) );

        if ( is_wp_error( $resp ) ) {
            $this->log( 'openai_upload_file: WP_Error', array( 'error' => $resp->get_error_message() ) );
            return null;
        }
        $response_code = wp_remote_retrieve_response_code( $resp );
        $response_body = wp_remote_retrieve_body( $resp );
        if ( $response_code !== 200 ) {
            $this->log( 'openai_upload_file: HTTP error', array( 'code' => $response_code, 'body' => substr( $response_body, 0, 800 ) ) );
            return null;
        }
        $data = json_decode( $response_body, true );
        if ( empty( $data['id'] ) ) {
            $this->log( 'openai_upload_file: missing file id', array( 'body' => substr( $response_body, 0, 800 ) ) );
            return null;
        }
        return $data['id'];
    }

    private function openai_create_batch( $file_id, $api_key, $window ) {
        $url = 'https://api.openai.com/v1/batches';
        $body = array(
            'input_file_id' => $file_id,
            'endpoint' => '/v1/chat/completions',
            'completion_window' => $window,
        );

        $resp = wp_remote_post( $url, array(
            'headers' => array(
                'Content-Type' => 'application/json',
                'Authorization' => 'Bearer ' . $api_key,
            ),
            'body' => wp_json_encode( $body ),
            'timeout' => 60,
        ) );

        if ( is_wp_error( $resp ) ) {
            $this->log( 'openai_create_batch: WP_Error', array( 'error' => $resp->get_error_message() ) );
            return null;
        }
        $data = json_decode( wp_remote_retrieve_body( $resp ), true );
        return $data['id'] ?? null;
    }

    private function openai_get_batch( $batch_id, $api_key ) {
        $url = 'https://api.openai.com/v1/batches/' . rawurlencode( $batch_id );
        $resp = wp_remote_get( $url, array(
            'headers' => array(
                'Authorization' => 'Bearer ' . $api_key,
            ),
            'timeout' => 60,
        ) );
        if ( is_wp_error( $resp ) ) {
            $this->log( 'openai_get_batch: WP_Error', array( 'error' => $resp->get_error_message() ) );
            return null;
        }
        return json_decode( wp_remote_retrieve_body( $resp ), true );
    }

    private function openai_download_file( $file_id, $api_key ) {
        $url = 'https://api.openai.com/v1/files/' . rawurlencode( $file_id ) . '/content';
        $resp = wp_remote_get( $url, array(
            'headers' => array(
                'Authorization' => 'Bearer ' . $api_key,
            ),
            'timeout' => 60,
        ) );
        if ( is_wp_error( $resp ) ) {
            $this->log( 'openai_download_file: WP_Error', array( 'error' => $resp->get_error_message() ) );
            return null;
        }
        return wp_remote_retrieve_body( $resp );
    }

    private function call_openai( $prompt, $api_key, $model ) {
        $url = 'https://api.openai.com/v1/chat/completions';
        $body = array(
            'model' => $model,
            'messages' => array(
                array( 'role' => 'system', 'content' => 'You are a translation engine. Preserve all HTML tags and shortcodes exactly. Only translate human-readable text.' ),
                array( 'role' => 'user', 'content' => $prompt ),
            ),
            'temperature' => 0.1,
        );

        $this->log( 'call_openai: request', array( 'model' => $model, 'prompt_length' => strlen( $prompt ) ) );

        $resp = wp_remote_post( $url, array(
            'headers' => array(
                'Content-Type' => 'application/json',
                'Authorization' => 'Bearer ' . $api_key,
            ),
            'body' => wp_json_encode( $body ),
            'timeout' => 60,
        ) );

        if ( is_wp_error( $resp ) ) {
            $this->log( 'call_openai: WP_Error', array( 'error' => $resp->get_error_message() ) );
            return null;
        }

        $response_code = wp_remote_retrieve_response_code( $resp );
        $response_body = wp_remote_retrieve_body( $resp );
        $data = json_decode( $response_body, true );

        if ( $response_code !== 200 ) {
            $retry_seconds = 0;
            $headers = wp_remote_retrieve_headers( $resp );
            if ( isset( $headers['retry-after'] ) ) {
                $retry_seconds = intval( $headers['retry-after'] );
            }
            $this->log( 'call_openai: HTTP error', array( 'code' => $response_code, 'retry_seconds' => $retry_seconds, 'body' => substr( $response_body, 0, 500 ) ) );
            if ( $response_code === 429 ) {
                return array( 'rate_limited' => true, 'retry_seconds' => max( 60, $retry_seconds ) );
            }
            return null;
        }

        if ( empty( $data['choices'][0]['message']['content'] ) ) {
            $this->log( 'call_openai: empty response', array( 'data' => $data ) );
            return null;
        }

        $text = $data['choices'][0]['message']['content'];
        $this->log( 'call_openai: success', array( 'response_length' => strlen( $text ) ) );
        return $text;
    }

    private function call_gemini( $prompt, $key, $override_model = null ) {
        $settings = $this->get_settings();
        if ( $override_model ) {
            $model = preg_replace( '#^models/#', '', sanitize_text_field( $override_model ) );
        } else {
            $model = isset( $settings['gemini_model'] ) && $settings['gemini_model'] ? $settings['gemini_model'] : 'gemini-3-flash-preview';
            $model = preg_replace( '#^models/#', '', $model );
        }

        $url = 'https://generativelanguage.googleapis.com/v1beta/models/' . rawurlencode( $model ) . ':generateContent?key=' . urlencode( $key );
        $body = array(
            'contents' => array(
                array( 'parts' => array( array( 'text' => $prompt ) ) )
            ),
            'generationConfig' => array(
                'temperature' => 0.1
            )
        );

        $this->log( 'call_gemini: request', array( 'model' => $model, 'key_prefix' => substr( $key, 0, 10 ) . '...', 'prompt_length' => strlen( $prompt ) ) );

            // If this key looks unavailable by usage counters, skip sending request
            if ( ! $this->key_is_available( $key ) ) {
                $this->log( 'call_gemini: skipped key because usage limit reached', array( 'key_prefix' => substr( $key, 0, 10 ) . '...' ) );
                return array( 'rate_limited' => true, 'retry_seconds' => $this->get_min_key_next_seconds( array( $key ) ) );
            }

        // Allow configurable timeout per-settings (seconds). Default to 60s but can be raised for large documents.
        $gemini_timeout = isset( $settings['gemini_timeout'] ) ? intval( $settings['gemini_timeout'] ) : 60;
        $this->log( 'call_gemini: using timeout', array( 'timeout_seconds' => $gemini_timeout ) );

        $resp = wp_remote_post( $url, array(
            'headers' => array( 'Content-Type' => 'application/json' ),
            'body' => wp_json_encode( $body ),
            'timeout' => $gemini_timeout,
        ) );

        if ( is_wp_error( $resp ) ) {
            $this->log( 'call_gemini: WP_Error', array( 'error' => $resp->get_error_message() ) );
            return null;
        }

        $response_code = wp_remote_retrieve_response_code( $resp );
        $response_body = wp_remote_retrieve_body( $resp );
        $data = json_decode( $response_body, true );

        if ( $response_code !== 200 ) {
            // Check for rate limit (429) and extract retry-after time
            $retry_seconds = 0;
            if ( $response_code === 429 && isset( $data['error']['message'] ) ) {
                // Extract "Please retry in X.Xs" from message
                if ( preg_match( '/retry in ([\d.]+)s/', $data['error']['message'], $matches ) ) {
                    $retry_seconds = ceil( floatval( $matches[1] ) );
                }
            }
            $this->log( 'call_gemini: HTTP error', array( 'code' => $response_code, 'retry_seconds' => $retry_seconds, 'body' => substr( $response_body, 0, 500 ) ) );
            // If rate-limited, set this key unavailable for that period
            if ( $response_code === 429 && $retry_seconds > 0 ) {
                $this->set_key_next_available( $key, current_time( 'timestamp' ) + intval( $retry_seconds ) );
                return array( 'rate_limited' => true, 'retry_seconds' => $retry_seconds );
            }
            return null;
        }

        if ( empty( $data['candidates'][0]['content']['parts'][0]['text'] ) ) {
            $this->log( 'call_gemini: empty response', array( 'data' => $data ) );
            return null;
        }

        $this->log( 'call_gemini: success', array( 'response_length' => strlen( $data['candidates'][0]['content']['parts'][0]['text'] ) ) );
        // increment usage counter for successful request
        $this->key_usage_increment( $key );
        return $data['candidates'][0]['content']['parts'][0]['text'];

        if ( empty( $data['candidates'][0]['content']['parts'][0]['text'] ) ) {
            $this->log( 'call_gemini: empty response', array( 'data' => $data ) );
            return null;
        }

        $this->log( 'call_gemini: success', array( 'response_length' => strlen( $data['candidates'][0]['content']['parts'][0]['text'] ) ) );
        return $data['candidates'][0]['content']['parts'][0]['text'];
    }

    /**
     * Split potentially large HTML content into chunks not exceeding $max_chars.
     * Tries to split on closing tags where possible to keep fragments well-formed.
     */
    private function chunk_html_by_size( $content, $max_chars = 30000 ) {
        $pieces = array();
        $len = strlen( $content );
        $pos = 0;
        while ( $pos < $len ) {
            $remaining_len = min( $max_chars, $len - $pos );
            $slice = substr( $content, $pos, $remaining_len );
            // Prefer splitting at the last closing tag within the slice
            $last_close = strrpos( $slice, '</' );
            if ( $last_close === false || $last_close < intval( $remaining_len * 0.3 ) ) {
                // Fall back to splitting at a space to avoid cutting words
                $last_space = strrpos( $slice, ' ' );
                if ( $last_space !== false && $last_space > intval( $remaining_len * 0.2 ) ) {
                    $cut = $last_space;
                } else {
                    $cut = $remaining_len;
                }
            } else {
                $endpos = strpos( $slice, '>', $last_close );
                if ( $endpos !== false ) {
                    $cut = $endpos + 1;
                } else {
                    $cut = $last_close;
                }
            }
            $pieces[] = substr( $content, $pos, $cut );
            $pos += $cut;
        }
        return $pieces;
    }

    public function add_query_vars( $vars ) {
        $vars[] = 'rbt_lang';
        return $vars;
    }

    public function add_rewrite_rules() {
        $codes = array_keys( $this->languages() );
        $codes = array_filter( $codes, function( $c ) { return $c !== 'en'; } );
        $regex = implode( '|', array_map( 'preg_quote', $codes ) );
        add_rewrite_rule( '(' . $regex . ')/([^/]+)/?$', 'index.php?name=$matches[2]&rbt_lang=$matches[1]', 'top' );
    }

    private function detect_lang_from_path() {
        $uri = isset( $_SERVER['REQUEST_URI'] ) ? parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ) : '';
        $trimmed = trim( $uri, '/' );
        if ( ! $trimmed ) {
            return 'en';
        }
        $first = strtok( $trimmed, '/' );
        $codes = array_keys( $this->languages() );
        if ( in_array( $first, $codes, true ) ) {
            return $first;
        }
        return 'en';
    }

    private function get_translation_id( $source_id, $lang, $post_type ) {
        global $wpdb;
        $table = $wpdb->prefix . 'rbt_translations';
        $row = $wpdb->get_row( $wpdb->prepare( "SELECT translated_post_id FROM {$table} WHERE source_post_id=%d AND lang=%s", $source_id, $lang ) );
        if ( $row && $row->translated_post_id ) {
            return intval( $row->translated_post_id );
        }
        return 0;
    }

    public function filter_page_link( $link, $post, $leavename ) {
        $lang = $this->detect_lang_from_path();
        if ( $lang === 'en' ) {
            return $link;
        }
        // $post may be an object or an ID; normalize safely
        $post_id = is_object( $post ) ? intval( $post->ID ) : intval( $post );
        if ( ! $post_id ) {
            return $link;
        }
        $translated_id = $this->get_translation_id( $post_id, $lang, 'page' );
        if ( $translated_id ) {
            return get_permalink( $translated_id );
        }
        return $link;
    }

    public function filter_post_link( $link, $post, $leavename ) {
        $lang = $this->detect_lang_from_path();
        if ( $lang === 'en' ) {
            return $link;
        }
        // $post may be an object or an ID; normalize safely
        $post_id = is_object( $post ) ? intval( $post->ID ) : intval( $post );
        if ( ! $post_id ) {
            return $link;
        }
        $translated_id = $this->get_translation_id( $post_id, $lang, 'post' );
        if ( $translated_id ) {
            return get_permalink( $translated_id );
        }
        return $link;
    }

    public function filter_content_links( $content ) {
        if ( is_admin() || empty( $content ) ) {
            return $content;
        }

        // Determine current viewing language from the post being displayed
        $current_lang = $this->get_current_viewing_lang();
        if ( $current_lang === 'en' ) {
            return $content;
        }

        // Parse site URL for matching
        $site_url = trailingslashit( get_site_url() );
        $site_host = parse_url( $site_url, PHP_URL_HOST );

        // Find all internal links in content
        $pattern = '#<a\s+([^>]*href=["\'])(' . preg_quote( $site_url, '#' ) . '|/|https?://[^/]*realbible\.tech)([^"\']*)["\']([^>]*)>#i';
        $content = preg_replace_callback( $pattern, function( $matches ) use ( $current_lang, $site_url ) {
            $before = $matches[1]; // href=" or href='
            $protocol_part = $matches[2]; // full URL or just /
            $path_and_query = $matches[3]; // the path + query part
            $after = $matches[4]; // rest of tag

            // Check if this is a chapter link (has ?book= or &book= parameter)
            if ( preg_match( '/[?&]book=([^&]+)/', $path_and_query, $book_match ) ) {
                // This is a chapter link - append lang parameter
                // Skip if already has lang parameter
                if ( strpos( $path_and_query, 'lang=' ) !== false ) {
                    return $matches[0];
                }
                // Append &lang= or ?lang= depending on whether there's already a query string
                $separator = strpos( $path_and_query, '?' ) !== false ? '&' : '?';
                $new_url = $protocol_part . $path_and_query . $separator . 'lang=' . $current_lang;
                return '<a ' . $before . $new_url . '"' . $after . '>';
            }

            // For regular post/page links, proceed with slug-based lookup
            // Parse just the path part (before query string)
            $path = strtok( $path_and_query, '?' );
            
            // Skip if already a language path
            $path_trimmed = trim( $path, '/' );
            $first_segment = $path_trimmed ? strtok( $path_trimmed, '/' ) : '';
            if ( in_array( $first_segment, array_keys( $this->languages() ), true ) ) {
                return $matches[0]; // already language-prefixed
            }

            // Try to find the post by slug
            $slug = basename( rtrim( $path, '/' ) );
            if ( ! $slug ) {
                return $matches[0];
            }

            // Look up the English post by slug (could be page or post)
            $english_post = get_page_by_path( $slug, OBJECT, array( 'page', 'post' ) );
            if ( ! $english_post ) {
                // Try post_name match
                $posts = get_posts( array(
                    'name' => $slug,
                    'post_type' => array( 'page', 'post' ),
                    'posts_per_page' => 1,
                    'post_status' => 'publish',
                ) );
                $english_post = ! empty( $posts ) ? $posts[0] : null;
            }

            if ( ! $english_post ) {
                return $matches[0]; // can't find source post
            }

            // Find the translation
            $translated_id = $this->get_translation_id( $english_post->ID, $current_lang, $english_post->post_type );
            if ( ! $translated_id ) {
                return $matches[0]; // no translation available
            }

            // Get the translated permalink
            $translated_permalink = get_permalink( $translated_id );
            if ( ! $translated_permalink ) {
                return $matches[0];
            }

            // Replace the href
            return '<a ' . $before . $translated_permalink . '"' . $after . '>';
        }, $content );

        return $content;
    }

    private function get_current_viewing_lang() {
        global $post;

        // Check if viewing a translated post
        if ( $post && isset( $post->ID ) ) {
            $lang = get_post_meta( $post->ID, 'rbt_lang', true );
            if ( $lang ) {
                return $lang;
            }
        }

        // Fallback to URL detection
        return $this->detect_lang_from_path();
    }

    /**
     * Translate menu item titles using the JSON map in settings
     */
    public function filter_nav_menu_item_title( $title, $item, $args, $depth ) {
        if ( is_admin() || empty( $title ) ) return $title;
        $lang = $this->get_current_viewing_lang();
        if ( $lang === 'en' ) return $title;

        $settings = $this->get_settings();
        $map = array();
        if ( ! empty( $settings['menu_label_translations'] ) ) {
            $decoded = json_decode( wp_unslash( $settings['menu_label_translations'] ), true );
            if ( is_array( $decoded ) ) $map = $decoded;
        }

        if ( isset( $map[ $title ] ) && isset( $map[ $title ][ $lang ] ) ) {
            return $map[ $title ][ $lang ];
        }

        return $title;
    }

    /**
     * Rewrite nav menu item hrefs to translated equivalents when available
     */
    public function filter_nav_menu_link( $atts, $item, $args, $depth ) {
        if ( is_admin() || empty( $atts['href'] ) ) return $atts;
        $lang = $this->get_current_viewing_lang();
        if ( $lang === 'en' ) return $atts;

        $href = $atts['href'];
        $site_url = trailingslashit( get_site_url() );

        // Check menu item object type (post/page) first
        if ( isset( $item->object_id ) && in_array( $item->object, array( 'page', 'post' ), true ) ) {
            $source_id = intval( $item->object_id );
            $translated_id = $this->get_translation_id( $source_id, $lang, $item->object );
            if ( $translated_id ) {
                $atts['href'] = get_permalink( $translated_id );
                return $atts;
            }
        }

        // If the theme/builder built menu items as custom links with the English title,
        // we also want to rewrite the label — handle that at the HTML level in a fallback below.

        // Otherwise handle custom links or read.realbible.tech chapter links
        $parsed = wp_parse_url( $href );
        if ( ! $parsed || ! isset( $parsed['path'] ) ) return $atts;

        // Chapter link detection by queryparam 'book'
        $query = isset( $parsed['query'] ) ? $parsed['query'] : '';
        if ( strpos( $query, 'book=' ) !== false ) {
            // Append lang param if not present
            if ( strpos( $query, 'lang=' ) === false ) {
                $separator = $query ? '&' : '';
                $new = $href . $separator . 'lang=' . $lang;
                $atts['href'] = $new;
            }
            return $atts;
        }

        // Try slug-based lookup on path
        $path = isset( $parsed['path'] ) ? $parsed['path'] : '';
        $slug = basename( rtrim( $path, '/' ) );
        if ( $slug ) {
            $english_post = get_page_by_path( $slug, OBJECT, array( 'page', 'post' ) );
            if ( ! $english_post ) {
                $posts = get_posts( array(
                    'name' => $slug,
                    'post_type' => array( 'page', 'post' ),
                    'posts_per_page' => 1,
                    'post_status' => 'publish',
                ) );
                $english_post = ! empty( $posts ) ? $posts[0] : null;
            }
            if ( $english_post ) {
                $translated_id = $this->get_translation_id( $english_post->ID, $lang, $english_post->post_type );
                if ( $translated_id ) {
                    $atts['href'] = get_permalink( $translated_id );
                    return $atts;
                }
            }
        }

        return $atts;
    }

    /**
     * Fallback: rewrite titles inside the rendered menu HTML for builders/themes
     */
    public function filter_nav_menu_items_html( $items, $args ) {
        if ( is_admin() || empty( $items ) ) return $items;
        $lang = $this->get_current_viewing_lang();
        if ( $lang === 'en' ) return $items;

        $settings = $this->get_settings();
        if ( empty( $settings['menu_label_translations'] ) ) return $items;

        $map = json_decode( wp_unslash( $settings['menu_label_translations'] ), true );
        if ( ! is_array( $map ) ) return $items;

        // Case-insensitive pattern map: look for >label< occurrences and replace with translated label
        foreach ( $map as $eng => $langs ) {
            if ( ! isset( $langs[ $lang ] ) ) continue;
            $translated = $langs[ $lang ];
            // Replace occurrences like ><whitespace>Stats< or >Stats< in anchor text
            $pattern = '/(>\s*)' . preg_quote( $eng, '/' ) . '(\s*<)/i';
            $replacement = '${1}' . $translated . '${2}';
            $items = preg_replace( $pattern, $replacement, $items );
        }

        return $items;
    }

    public function output_rbt_lang_meta() {
        // Output a simple meta tag so frontend scripts can detect page language.
        if ( is_admin() ) return;
        global $post;
        $lang = '';
        if ( $post && $m = get_post_meta( $post->ID, 'rbt_lang', true ) ) {
            $lang = $m;
        } else {
            $lang = $this->detect_lang_from_path();
        }
        if ( $lang ) {
            echo "<meta name=\"rbt-lang\" content=\"" . esc_attr( $lang ) . "\">\n";
        }
    }

    public function output_rbt_lang_body_marker() {
        // Emit a hidden element with data-rbt-lang for JS that runs after body open.
        if ( is_admin() ) return;
        global $post;
        $lang = '';
        if ( $post && $m = get_post_meta( $post->ID, 'rbt_lang', true ) ) {
            $lang = $m;
        } else {
            $lang = $this->detect_lang_from_path();
        }
        if ( $lang ) {
            echo '<div style="display:none" data-rbt-lang="' . esc_attr( $lang ) . '"></div>' . "\n";
        }
    }

    public function handle_lang_routes( $wp ) {
        if ( is_admin() ) {
            return;
        }

        $path = trim( $wp->request, '/' );
        if ( ! $path ) {
            return;
        }

        $segments = explode( '/', $path );
        $lang = $segments[0] ?? '';
        $codes = array_keys( $this->languages() );
        if ( ! $lang || ! in_array( $lang, $codes, true ) ) {
            return;
        }

        $slug = $segments[1] ?? '';
        if ( ! $slug ) {
            return;
        }

        // Try translated post by source slug
        $translated = get_posts( array(
            'post_type' => 'post',
            'posts_per_page' => 1,
            'post_status' => 'publish',
            'meta_query' => array(
                array( 'key' => 'rbt_lang', 'value' => $lang ),
                array( 'key' => 'rbt_source_slug', 'value' => $slug ),
            )
        ) );
        if ( $translated ) {
            $wp->query_vars = array( 'p' => $translated[0]->ID, 'post_type' => 'post', 'name' => $translated[0]->post_name );
            return;
        }

        // Try translated page by path
        $page = get_page_by_path( $slug );
        if ( $page ) {
            $translated_id = $this->get_translation_id( $page->ID, $lang, 'page' );
            if ( $translated_id ) {
                $wp->query_vars = array( 'page_id' => $translated_id );
                return;
            }
        }
    }

    public function disable_lang_canonical_redirect( $redirect_url, $requested_url ) {
        $path = parse_url( $requested_url, PHP_URL_PATH );
        $trimmed = trim( $path ?? '', '/' );
        $first = $trimmed ? strtok( $trimmed, '/' ) : '';
        if ( $first && in_array( $first, array_keys( $this->languages() ), true ) ) {
            return false;
        }
        return $redirect_url;
    }
}

RBT_Translator::instance();
