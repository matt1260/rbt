<?php
/**
 * Header template — Sanctum-styled navigation for inner pages
 *
 * @package RBT_Sanctum
 */

if ( ! defined( 'ABSPATH' ) ) exit;

$lang       = rbt_sanctum_detect_lang();
$home_url   = home_url( '/' );
$theme_uri  = get_stylesheet_directory_uri();
$paypal_url = 'https://www.paypal.com/donate/?hosted_button_id=6LHHSLKJCY4RY';
?>
<!doctype html>
<html <?php language_attributes(); ?>>
<head>
  <meta charset="<?php bloginfo( 'charset' ); ?>" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <?php wp_head(); ?>
</head>
<body <?php body_class( 'sanctum-inner' ); ?>>
<?php wp_body_open(); ?>

<nav class="sanctum-wp-nav" id="sanctum-nav">
  <a href="<?php echo esc_url( $home_url ); ?>" class="sanctum-wp-nav-logo">
    <img src="<?php echo esc_url( $theme_uri . '/assets/nun.png' ); ?>" alt="nun" />
    <span>Real Bible Project</span>
  </a>

  <div class="sanctum-wp-nav-right">
    <ul class="sanctum-wp-nav-links" id="sanctum-nav-links">
      <li><a href="https://read.realbible.tech/statistics/">Statistics</a></li>
      <li><a href="https://www.realbible.tech/let-there-be-science/">Science</a></li>
      <li><a href="https://www.realbible.tech/about/">About</a></li>
      <li><a href="https://www.realbible.tech/methodology/">Methodology</a></li>
      <li><a href="#support-this-work">Support</a></li>
    </ul>

    <?php if ( $lang && $lang !== 'en' ) : ?>
      <a href="<?php echo esc_url( $home_url ); ?>" class="sanctum-wp-lang-toggle">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
        <?php echo esc_html( strtoupper( $lang ) ); ?>
      </a>
    <?php endif; ?>

    <button class="sanctum-wp-hamburger" id="sanctum-hamburger" aria-label="Toggle menu" onclick="document.getElementById('sanctum-nav-links').classList.toggle('open')">
      <span></span><span></span><span></span>
    </button>
  </div>
</nav>
