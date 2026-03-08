<?php
/**
 * 404 template
 *
 * @package RBT_Sanctum
 */

get_header();
?>

<main class="sanctum-wp-content">
  <div class="sanctum-wp-404">
    <h1>404</h1>
    <p>The page you're looking for doesn't exist.</p>
    <p><a href="<?php echo esc_url( home_url( '/' ) ); ?>" class="sanctum-wp-read-more">Return Home →</a></p>
  </div>
</main>

<?php get_footer(); ?>
