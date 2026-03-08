<?php
/**
 * Template Name: Northflank Stats Dashboard
 *
 * @package RBT_Sanctum
 */

get_header();
?>

<main class="sanctum-wp-content" style="max-width: 1200px;">
  <h1><?php the_title(); ?></h1>
  <?php while ( have_posts() ) : the_post(); ?>
    <article class="entry-content">
      <?php the_content(); ?>
    </article>
  <?php endwhile; ?>
</main>

<?php get_footer(); ?>
