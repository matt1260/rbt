<?php
/**
 * Page template — standard WordPress pages
 *
 * @package RBT_Sanctum
 */

get_header();
?>

<main class="sanctum-wp-content">
  <?php while ( have_posts() ) : the_post(); ?>

    <h1><?php the_title(); ?></h1>

    <article class="entry-content">
      <?php the_content(); ?>
    </article>

  <?php endwhile; ?>
</main>

<?php get_footer(); ?>
