<?php
/**
 * Single post template
 *
 * @package RBT_Sanctum
 */

get_header();
?>

<main class="sanctum-wp-content">
  <?php while ( have_posts() ) : the_post(); ?>

    <h1><?php the_title(); ?></h1>

    <div class="sanctum-wp-meta">
      <time datetime="<?php echo get_the_date( 'c' ); ?>"><?php echo get_the_date(); ?></time>
      <?php if ( get_the_category_list() ) : ?>
        <span><?php the_category( ', ' ); ?></span>
      <?php endif; ?>
    </div>

    <article class="entry-content">
      <?php the_content(); ?>
    </article>

    <?php
    the_post_navigation( array(
      'prev_text' => '<span class="sanctum-wp-read-more">← %title</span>',
      'next_text' => '<span class="sanctum-wp-read-more">%title →</span>',
    ) );
    ?>

  <?php endwhile; ?>
</main>

<?php get_footer(); ?>
