<?php
/**
 * Front Page Template — React SPA takeover
 *
 * WordPress automatically uses front-page.php when a static front page is set
 * OR when "Your latest posts" is selected. This bypasses header/footer and hands
 * the entire page to the Vite-built React Sanctum app.
 *
 * @package RBT_Sanctum
 */

if ( ! defined( 'ABSPATH' ) ) exit;

$theme_uri  = get_stylesheet_directory_uri();
$theme_dir  = get_stylesheet_directory();
$react_dir  = $theme_dir . '/react';
$react_uri  = $theme_uri . '/react';

// Detect language from URL path (e.g., /es/, /fr/)
$lang = rbt_sanctum_detect_lang();
?>
<!doctype html>
<html <?php language_attributes(); ?>>
<head>
  <meta charset="<?php bloginfo( 'charset' ); ?>" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title><?php wp_title( '—', true, 'right' ); bloginfo( 'name' ); ?></title>

  <!-- Font Awesome (matches React build) -->
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" />

  <?php
  // Enqueue the React CSS
  $css_file = $react_dir . '/sanctum.css';
  if ( file_exists( $css_file ) ) {
    $css_ver = filemtime( $css_file );
    echo '<link rel="stylesheet" href="' . esc_url( $react_uri . '/sanctum.css' ) . '?v=' . $css_ver . '" />' . "\n";
  }

  // Prevent FOUC: keep root hidden until React signals readiness.
  echo '<style id="rbt-sanctum-preload">body.sanctum-frontpage #root{visibility:hidden;opacity:0;}body.sanctum-frontpage.rbt-sanctum-ready #root{visibility:visible;opacity:1;}</style>' . "\n";

  // Override the hero background image URL so CSS url('/shewhohovers.jpg') resolves
  echo '<style>.sanctum-hero { background-image: url(' . esc_url( $react_uri . '/shewhohovers.jpg' ) . ') !important; }</style>' . "\n";

  // Tell the React app where theme assets live
  echo '<script>window.__RBT_THEME_URI = ' . json_encode( $react_uri ) . ';</script>' . "\n";

  wp_head();
  ?>
</head>
<body <?php body_class( 'sanctum-frontpage' ); ?>>
<?php wp_body_open(); ?>

  <div id="root"></div>

  <?php
  // Load the React JS bundle
  $js_file = $react_dir . '/sanctum.js';
  if ( file_exists( $js_file ) ) {
    $js_ver = filemtime( $js_file );
    echo '<script type="module" crossorigin src="' . esc_url( $react_uri . '/sanctum.js' ) . '?v=' . $js_ver . '"></script>' . "\n";
  }

  wp_footer();
  ?>
</body>
</html>
