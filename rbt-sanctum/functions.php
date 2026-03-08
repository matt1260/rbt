<?php
/**
 * RBT Sanctum Theme — Functions
 *
 * Standalone theme (no parent). Migrates all neve-child functionality:
 *   - Language-aware routing & hreflang
 *   - Northflank dashboard shortcode
 *   - SEO meta
 *   - Asset enqueue
 *
 * @package RBT_Sanctum
 */

if ( ! defined( 'ABSPATH' ) ) exit;

/* ──────────────────────────────────────────────
   1. THEME SETUP
   ────────────────────────────────────────────── */

function rbt_sanctum_setup() {
    add_theme_support( 'title-tag' );
    add_theme_support( 'post-thumbnails' );
    add_theme_support( 'html5', array( 'search-form', 'comment-form', 'comment-list', 'gallery', 'caption' ) );
    add_theme_support( 'automatic-feed-links' );
    add_theme_support( 'responsive-embeds' );
    add_theme_support( 'align-wide' );
    add_theme_support( 'wp-block-styles' );
    add_theme_support( 'editor-styles' );

    register_nav_menus( array(
        'primary'              => __( 'Primary Navigation', 'rbt-sanctum' ),
        'rbt-footer-about'     => __( 'Footer – About', 'rbt-sanctum' ),
        'rbt-footer-resources' => __( 'Footer – Resources', 'rbt-sanctum' ),
        'rbt-footer-quick'     => __( 'Footer – Quick Links', 'rbt-sanctum' ),
    ) );
}
add_action( 'after_setup_theme', 'rbt_sanctum_setup' );


/* ──────────────────────────────────────────────
   2. LANGUAGE HELPERS
   ────────────────────────────────────────────── */

function rbt_sanctum_get_language_prefixes() {
    return array(
        'en','es','fr','de','it','pt','ru','ar','zh','hi','pl','uk','ro','nl',
        'sv','hu','cs','tr','ja','ko','vi','th','id','bn','ur','fa','pa','mr',
        'ta','sw','ha','yo','ig','am','om',
    );
}

function rbt_sanctum_get_languages() {
    return array(
        'en' => 'English',
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
        'om' => 'Afaan Oromoo',
    );
}

function rbt_sanctum_detect_lang() {
    $request_path = isset( $_SERVER['REQUEST_URI'] )
        ? parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH )
        : '';
    $trimmed       = trim( $request_path, '/' );
    $first_segment = $trimmed ? strtok( $trimmed, '/' ) : '';
    $prefixes      = rbt_sanctum_get_language_prefixes();

    if ( $first_segment && in_array( $first_segment, $prefixes, true ) ) {
        return $first_segment;
    }
    return 'en';
}


/* ──────────────────────────────────────────────
   3. ENQUEUE STYLES & SCRIPTS
   ────────────────────────────────────────────── */

function rbt_sanctum_enqueue_assets() {
    // Main theme stylesheet (inner pages)
    wp_enqueue_style(
        'rbt-sanctum-style',
        get_stylesheet_uri(),
        array(),
        wp_get_theme()->get( 'Version' )
    );

    // Font Awesome
    wp_enqueue_style(
        'font-awesome',
        'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',
        array(),
        '6.5.1'
    );

    // Language selector (site-wide)
    rbt_sanctum_enqueue_if_exists( 'rbt-language-selector', 'js/language_selector.js' );

    // Stats (site-wide)
    rbt_sanctum_enqueue_if_exists( 'rbt-stats', 'js/stats.js' );

    // Searchbar — front page & language homepages only
    $prefixes = rbt_sanctum_get_language_prefixes();
    $request  = isset( $_SERVER['REQUEST_URI'] ) ? parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ) : '';
    $trimmed  = trim( $request, '/' );
    $first    = $trimmed ? strtok( $trimmed, '/' ) : '';

    $is_lang_home = ( $trimmed === '' ) || ( $first && in_array( $first, $prefixes, true ) && ( $trimmed === $first || $trimmed === $first . '/' ) );

    if ( is_front_page() || $is_lang_home ) {
        rbt_sanctum_enqueue_if_exists( 'rbt-searchbar', 'js/searchbar.js' );
    }
}
add_action( 'wp_enqueue_scripts', 'rbt_sanctum_enqueue_assets', 20 );

/**
 * Helper: enqueue a JS file from the theme dir if it exists.
 */
function rbt_sanctum_enqueue_if_exists( $handle, $relative_path, $deps = array() ) {
    $path = get_stylesheet_directory() . '/' . $relative_path;
    if ( file_exists( $path ) ) {
        wp_enqueue_script(
            $handle,
            get_stylesheet_directory_uri() . '/' . $relative_path,
            $deps,
            filemtime( $path ),
            true
        );
    }
}

/**
 * Remove problematic video player scripts from plugins / parent themes.
 */
function rbt_sanctum_remove_video_scripts() {
    global $wp_scripts;
    if ( ! ( $wp_scripts instanceof WP_Scripts ) ) return;

    $targets = array( 'jquery.mb.YTPlayer.min.js', 'ut-videoplayer.min.js' );
    foreach ( $wp_scripts->registered as $handle => $script ) {
        $src = isset( $script->src ) ? $script->src : '';
        foreach ( $targets as $t ) {
            if ( $src && false !== strpos( $src, $t ) ) {
                wp_dequeue_script( $handle );
                wp_deregister_script( $handle );
            }
        }
    }
}
add_action( 'wp_enqueue_scripts', 'rbt_sanctum_remove_video_scripts', 100 );


/* ──────────────────────────────────────────────
   4. LANGUAGE-AWARE ROUTING
   (Migrated from neve-child functions.php)
   ────────────────────────────────────────────── */

function rbt_sanctum_get_translation_id( $source_id, $lang, $post_type ) {
    static $cache = array();
    $key = $source_id . '|' . $lang . '|' . $post_type;
    if ( isset( $cache[ $key ] ) ) return $cache[ $key ];

    $posts = get_posts( array(
        'post_type'      => $post_type,
        'posts_per_page' => 1,
        'post_status'    => 'publish',
        'meta_query'     => array(
            array( 'key' => 'rbt_source_id', 'value' => (string) $source_id ),
            array( 'key' => 'rbt_lang', 'value' => $lang ),
        ),
        'fields' => 'ids',
    ) );

    $cache[ $key ] = $posts ? (int) $posts[0] : 0;
    return $cache[ $key ];
}

function rbt_sanctum_filter_page_link( $link, $post, $leavename ) {
    $lang = rbt_sanctum_detect_lang();
    if ( $lang === 'en' ) return $link;

    $post_id = 0;
    if ( is_object( $post ) && isset( $post->ID ) ) {
        $post_id = (int) $post->ID;
    } elseif ( is_numeric( $post ) ) {
        $post_id = (int) $post;
    }
    if ( ! $post_id ) return $link;

    $translated_id = rbt_sanctum_get_translation_id( $post_id, $lang, 'page' );
    return $translated_id ? get_permalink( $translated_id ) : $link;
}
add_filter( 'page_link', 'rbt_sanctum_filter_page_link', 10, 3 );

function rbt_sanctum_filter_post_link( $link, $post, $leavename ) {
    $lang = rbt_sanctum_detect_lang();
    if ( $lang === 'en' ) return $link;

    $post_id = 0;
    if ( is_object( $post ) && isset( $post->ID ) ) {
        $post_id = (int) $post->ID;
    } elseif ( is_numeric( $post ) ) {
        $post_id = (int) $post;
    }
    if ( ! $post_id ) return $link;

    $translated_id = rbt_sanctum_get_translation_id( $post_id, $lang, 'post' );
    return $translated_id ? get_permalink( $translated_id ) : $link;
}
add_filter( 'post_link', 'rbt_sanctum_filter_post_link', 10, 3 );

function rbt_sanctum_find_translated_post_by_slug( $slug, $lang ) {
    $posts = get_posts( array(
        'post_type'      => 'post',
        'posts_per_page' => 1,
        'post_status'    => 'publish',
        'meta_query'     => array(
            array( 'key' => 'rbt_lang', 'value' => $lang ),
            array( 'key' => 'rbt_source_slug', 'value' => $slug ),
        ),
    ) );
    if ( $posts ) return $posts[0];

    $fallback = get_page_by_path( $slug . '-' . $lang, OBJECT, 'post' );
    return $fallback ?: null;
}

function rbt_sanctum_parse_language_request( $wp ) {
    if ( is_admin() ) return;

    $path = trim( $wp->request, '/' );
    if ( ! $path ) return;

    $segments = explode( '/', $path );
    $lang     = $segments[0] ?? '';
    if ( ! $lang || ! in_array( $lang, rbt_sanctum_get_language_prefixes(), true ) ) return;

    $slug = $segments[1] ?? '';

    // Language home (e.g., /es/) → show front page
    if ( ! $slug ) {
        // Let WordPress resolve the front page normally; we'll detect lang in front-page.php
        return;
    }

    // 1) Language child page: /{lang}/{slug}/
    $page = get_page_by_path( $lang . '/' . $slug );
    if ( $page ) {
        $wp->query_vars = array( 'page_id' => $page->ID );
        return;
    }

    // 2) Translated post by meta
    $translated_post = rbt_sanctum_find_translated_post_by_slug( $slug, $lang );
    if ( $translated_post ) {
        $wp->query_vars = array( 'p' => $translated_post->ID, 'post_type' => 'post', 'name' => $translated_post->post_name );
        return;
    }

    // 3) Fallback to English page/post
    $page_en = get_page_by_path( $slug );
    if ( $page_en ) {
        $wp->query_vars = array( 'page_id' => $page_en->ID );
        return;
    }
    $post_en = get_page_by_path( $slug, OBJECT, 'post' );
    if ( $post_en ) {
        $wp->query_vars = array( 'p' => $post_en->ID, 'post_type' => 'post', 'name' => $post_en->post_name );
        return;
    }
}
add_action( 'parse_request', 'rbt_sanctum_parse_language_request', 1 );

function rbt_sanctum_disable_lang_canonical_redirect( $redirect_url, $requested_url ) {
    $path    = parse_url( $requested_url, PHP_URL_PATH );
    $trimmed = trim( $path ?? '', '/' );
    $first   = $trimmed ? strtok( $trimmed, '/' ) : '';
    if ( $first && in_array( $first, rbt_sanctum_get_language_prefixes(), true ) ) {
        return false;
    }
    return $redirect_url;
}
add_filter( 'redirect_canonical', 'rbt_sanctum_disable_lang_canonical_redirect', 10, 2 );


/* ──────────────────────────────────────────────
   5. LANGUAGE HOME → FRONT PAGE INTERCEPT
   Make /{lang}/ render front-page.php with React
   ────────────────────────────────────────────── */

function rbt_sanctum_lang_home_template( $template ) {
    $path     = isset( $_SERVER['REQUEST_URI'] ) ? parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ) : '';
    $trimmed  = trim( $path, '/' );
    $prefixes = rbt_sanctum_get_language_prefixes();

    // If the path is exactly a language code (e.g., "es" or "fr")
    if ( $trimmed && in_array( $trimmed, $prefixes, true ) ) {
        $front = locate_template( 'front-page.php' );
        if ( $front ) return $front;
    }

    return $template;
}
add_filter( 'template_include', 'rbt_sanctum_lang_home_template', 99 );


/* ──────────────────────────────────────────────
   6. SEO — HREFLANG + META DESCRIPTION
   ────────────────────────────────────────────── */

function rbt_sanctum_hreflang_tags() {
    if ( ! ( is_singular() || is_front_page() || is_home() ) ) return;

    $languages = array( 'en','es','fr','de','pt','it','nl','ru','zh','ja','ko','ar','hi','bn','ur','vi','tr','ta','te','th','sw','sv','pl','fa','uk' );

    $current_url = explode( '?', 'https://' . $_SERVER['HTTP_HOST'] . $_SERVER['REQUEST_URI'] )[0];
    $base_url    = preg_replace( '/https:\/\/[^\/]+\/[a-z]{2}\//', 'https://' . $_SERVER['HTTP_HOST'] . '/', $current_url );

    echo '<link rel="alternate" href="' . esc_url( $base_url ) . '" hreflang="x-default" />' . "\n";
    echo '<link rel="alternate" href="' . esc_url( $base_url ) . '" hreflang="en" />' . "\n";

    foreach ( $languages as $lang ) {
        if ( $lang !== 'en' ) {
            $lang_url = str_replace( home_url( '/' ), home_url( '/' . $lang . '/' ), $base_url );
            echo '<link rel="alternate" href="' . esc_url( $lang_url ) . '" hreflang="' . esc_attr( $lang ) . '" />' . "\n";
        }
    }
}
add_action( 'wp_head', 'rbt_sanctum_hreflang_tags', 1 );

function rbt_sanctum_meta_description() {
    if ( ! is_singular() ) return;
    global $post;
    $excerpt = wp_strip_all_tags( $post->post_content );
    $excerpt = substr( $excerpt, 0, 160 );
    echo '<meta name="description" content="' . esc_attr( $excerpt ) . '…" />' . "\n";
}
add_action( 'wp_head', 'rbt_sanctum_meta_description', 2 );


/* ──────────────────────────────────────────────
   7. NORTHFLANK STATS DASHBOARD
   (Shortcode: [rbt_northflank_stats])
   ────────────────────────────────────────────── */

function rbt_sanctum_northflank_assets() {
    if ( ! is_page_template( 'page-northflank-stats.php' ) ) return;

    wp_enqueue_script(
        'chart-js',
        'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
        array(),
        '4.4.7',
        true
    );

    rbt_sanctum_enqueue_if_exists( 'rbt-northflank-stats-page', 'js/northflank-stats-page.js', array( 'chart-js' ) );

    $endpoint = apply_filters(
        'rbt_northflank_stats_endpoint',
        'https://rbtproject.up.railway.app/api/northflank/stats/'
    );

    wp_localize_script( 'rbt-northflank-stats-page', 'RBTNorthflankStatsConfig', array(
        'endpoint'          => esc_url_raw( $endpoint ),
        'refreshIntervalMs' => 300000,
    ) );
}
add_action( 'wp_enqueue_scripts', 'rbt_sanctum_northflank_assets', 40 );

function rbt_sanctum_northflank_shortcode() {
    ob_start();
    ?>
    <div class="rbt-nf-dashboard" id="rbt-nf-dashboard">
        <div class="rbt-nf-header">
            <h2>Infrastructure Dashboard</h2>
            <button type="button" class="rbt-nf-refresh" id="rbt-nf-refresh">Refresh</button>
        </div>
        <div class="rbt-nf-summary" id="rbt-nf-summary">
            <div class="rbt-nf-card"><span class="label">Services</span><span class="value" id="nf-services-total">--</span></div>
            <div class="rbt-nf-card"><span class="label">Addons</span><span class="value" id="nf-addons-total">--</span></div>
            <div class="rbt-nf-card"><span class="label">Uptime Ratio</span><span class="value" id="nf-uptime-ratio">--</span></div>
            <div class="rbt-nf-card"><span class="label">Running Units</span><span class="value" id="nf-running-units">--</span></div>
        </div>
        <div class="rbt-nf-grid">
            <section class="rbt-nf-panel"><h3>Service Status</h3><canvas id="nf-service-status-chart" height="220"></canvas></section>
            <section class="rbt-nf-panel"><h3>Addon Status</h3><canvas id="nf-addon-status-chart" height="220"></canvas></section>
            <section class="rbt-nf-panel"><h3>Service Types</h3><canvas id="nf-service-types-chart" height="240"></canvas></section>
            <section class="rbt-nf-panel"><h3>Reach Regions</h3><canvas id="nf-regions-chart" height="240"></canvas></section>
            <section class="rbt-nf-panel rbt-nf-panel-wide"><h3>Uptime / Downtime (Recent)</h3><canvas id="nf-uptime-chart" height="120"></canvas></section>
            <section class="rbt-nf-panel rbt-nf-panel-wide"><h3>Compute Capacity</h3><div class="rbt-nf-capacity" id="nf-capacity">Loading...</div></section>
            <section class="rbt-nf-panel rbt-nf-panel-wide"><h3>Cost Data</h3><pre class="rbt-nf-costs" id="nf-costs">Loading...</pre></section>
        </div>
        <div class="rbt-nf-footer" id="nf-meta"></div>
        <div class="rbt-nf-warning" id="nf-warning" hidden></div>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode( 'rbt_northflank_stats', 'rbt_sanctum_northflank_shortcode' );


/* ──────────────────────────────────────────────
   8. PAGE TEMPLATE: Northflank Stats
   ────────────────────────────────────────────── */

function rbt_sanctum_register_page_templates( $templates ) {
    $templates['page-northflank-stats.php'] = 'Northflank Stats Dashboard';
    return $templates;
}
add_filter( 'theme_page_templates', 'rbt_sanctum_register_page_templates' );


/* ──────────────────────────────────────────────
   9. CONTENT WIDTH
   ────────────────────────────────────────────── */

function rbt_sanctum_content_width() {
    $GLOBALS['content_width'] = apply_filters( 'rbt_sanctum_content_width', 860 );
}
add_action( 'after_setup_theme', 'rbt_sanctum_content_width', 0 );


/* ──────────────────────────────────────────────
   10. CUSTOMIZER — Add accent color option
   ────────────────────────────────────────────── */

function rbt_sanctum_customizer( $wp_customize ) {
    $wp_customize->add_section( 'rbt_sanctum_colors', array(
        'title'    => __( 'Sanctum Colors', 'rbt-sanctum' ),
        'priority' => 30,
    ) );

    $wp_customize->add_setting( 'rbt_sanctum_gold', array(
        'default'           => '#b78550',
        'sanitize_callback' => 'sanitize_hex_color',
    ) );

    $wp_customize->add_control( new WP_Customize_Color_Control( $wp_customize, 'rbt_sanctum_gold', array(
        'label'   => __( 'Accent Gold', 'rbt-sanctum' ),
        'section' => 'rbt_sanctum_colors',
    ) ) );
}
add_action( 'customize_register', 'rbt_sanctum_customizer' );

function rbt_sanctum_custom_css() {
    $gold = get_theme_mod( 'rbt_sanctum_gold', '#b78550' );
    if ( $gold !== '#b78550' ) {
        echo '<style>:root { --gold: ' . esc_attr( $gold ) . '; }</style>' . "\n";
    }
}
add_action( 'wp_head', 'rbt_sanctum_custom_css', 99 );


/* ──────────────────────────────────────────────
   11. WIDGET AREAS
   ────────────────────────────────────────────── */

function rbt_sanctum_widgets_init() {
    register_sidebar( array(
        'name'          => __( 'Sidebar', 'rbt-sanctum' ),
        'id'            => 'sidebar-1',
        'before_widget' => '<div class="sanctum-widget">',
        'after_widget'  => '</div>',
        'before_title'  => '<h4 class="sanctum-widget-title">',
        'after_title'   => '</h4>',
    ) );
}
add_action( 'widgets_init', 'rbt_sanctum_widgets_init' );


/* ──────────────────────────────────────────────
   12. REST API PROXY – update count
   Proxies /wp-json/rbt/v1/update-count → Django
   so the React front-page avoids cross-origin
   issues when Railway returns 503 without CORS.
   ────────────────────────────────────────────── */
add_action( 'rest_api_init', function () {
    register_rest_route( 'rbt/v1', '/update-count', array(
        'methods'             => 'GET',
        'callback'            => 'rbt_proxy_update_count',
        'permission_callback' => '__return_true',
    ) );
} );

function rbt_proxy_update_count( WP_REST_Request $request ) {
    $response = wp_remote_get(
        'https://read.realbible.tech/update_count/',
        array(
            'timeout'   => 5,
            'sslverify' => true,
        )
    );

    if ( is_wp_error( $response ) ) {
        return new WP_REST_Response( array( 'updateCount' => 0 ), 200 );
    }

    $code = wp_remote_retrieve_response_code( $response );
    $body = wp_remote_retrieve_body( $response );
    $data = json_decode( $body, true );

    if ( $code !== 200 || ! isset( $data['updateCount'] ) ) {
        return new WP_REST_Response( array( 'updateCount' => 0 ), 200 );
    }

    return new WP_REST_Response( array( 'updateCount' => (int) $data['updateCount'] ), 200 );
}

/* ──────────────────────────────────────────────
   COMMENTARY POSTS SHORTCODE
   Usage: [rbt_commentary_posts]
   ────────────────────────────────────────────── */

function rbt_commentary_posts_shortcode( $atts ) {
    $atts = shortcode_atts( array(
        'posts_per_page' => -1,
        'category_name'  => 'commentary',
    ), $atts, 'rbt_commentary_posts' );

    $query = new WP_Query( array(
        'post_type'      => 'post',
        'post_status'    => 'publish',
        'category_name'  => $atts['category_name'],
        'posts_per_page' => (int) $atts['posts_per_page'],
        'orderby'        => 'date',
        'order'          => 'DESC',
    ) );

    if ( ! $query->have_posts() ) {
        return '<p style="color:#8a7e70;font-style:italic;">No commentary posts found.</p>';
    }

    ob_start();
    ?>
    <style>
    .rbt-notes-layout {
        display: flex;
        gap: 3rem;
        align-items: flex-start;
        margin: 1rem 0 2rem;
    }
    .rbt-notes-list-col {
        flex: 1 1 0;
        min-width: 0;
    }
    .rbt-notes-graphic-col {
        flex: 0 0 auto;
        width: 454px;
        position: sticky;
        top: 5rem;
    }
    .rbt-notes-graphic-col img {
        width: 100%;
        height: auto;
        display: block;
        border: 1px solid rgba(183,133,80,0.2);
    }
    .rbt-notes-list {
        list-style: none;
        margin: 0;
        padding: 0;
    }
    .rbt-notes-list li {
        border-bottom: 1px solid rgba(183,133,80,0.15);
    }
    .rbt-notes-list li:last-child {
        border-bottom: none;
    }
    .rbt-notes-item {
        display: flex;
        flex-direction: column;
        padding: 0.65rem 0;
        gap: 0.15rem;
        text-decoration: none;
        color: inherit;
        transition: padding-left 0.15s;
    }
    .rbt-notes-item:hover {
        padding-left: 0.35rem;
    }
    .rbt-notes-item-title {
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-size: 1.05rem;
        font-weight: 600;
        line-height: 1.3;
        color: #1a1611;
        transition: color 0.15s;
    }
    .rbt-notes-item:hover .rbt-notes-item-title {
        color: #b78550;
    }
    .rbt-notes-item-date {
        font-size: 0.68rem;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        color: #8a7e70;
    }
    @media (max-width: 640px) {
        .rbt-notes-layout { flex-direction: column; }
        .rbt-notes-graphic-col { width: 100%; position: static; }
        .rbt-notes-graphic-col img { max-width: 260px; margin: 0 auto; }
    }
    </style>
    <div class="rbt-notes-layout">
        <ul class="rbt-notes-list rbt-notes-list-col">
        <?php while ( $query->have_posts() ) : $query->the_post(); ?>
            <li>
                <a class="rbt-notes-item" href="<?php the_permalink(); ?>">
                    <span class="rbt-notes-item-title"><?php the_title(); ?></span>
                    <span class="rbt-notes-item-date"><?php echo esc_html( get_the_date( 'F j, Y' ) ); ?></span>
                </a>
            </li>
        <?php endwhile; wp_reset_postdata(); ?>
        </ul>
        <div class="rbt-notes-graphic-col">
            <img src="https://www.realbible.tech/wp-content/uploads/2022/05/history-of-Hebrew.png"
                 alt="History of the Hebrew Language"
                 loading="lazy">
        </div>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode( 'rbt_commentary_posts', 'rbt_commentary_posts_shortcode' );

/* ──────────────────────────────────────────────
   REMOVE POST PREV/NEXT NAVIGATION
   ────────────────────────────────────────────── */
add_filter( 'the_post_navigation', '__return_empty_string', 99 );
add_filter( 'next_post_link',      '__return_empty_string', 99 );
add_filter( 'previous_post_link',  '__return_empty_string', 99 );
