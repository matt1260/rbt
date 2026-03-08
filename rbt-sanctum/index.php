<?php
/**
 * Default template — blog posts index
 *
 * @package RBT_Sanctum
 */

get_header();
?>

<main class="sanctum-wp-content">

  <?php if ( is_home() && ! is_front_page() ) : ?>
    <h1>Blog</h1>
  <?php endif; ?>

  <?php if ( have_posts() ) : ?>
    <ul class="sanctum-wp-post-list">
      <?php while ( have_posts() ) : the_post(); ?>
        <li class="sanctum-wp-post-item">
          <h2><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h2>
          <div class="sanctum-wp-meta">
            <time datetime="<?php echo get_the_date( 'c' ); ?>"><?php echo get_the_date(); ?></time>
          </div>
          <div class="sanctum-wp-post-excerpt">
            <?php the_excerpt(); ?>
          </div>
          <a href="<?php the_permalink(); ?>" class="sanctum-wp-read-more">Read More →</a>
        </li>
      <?php endwhile; ?>
    </ul>

    <div class="sanctum-wp-pagination">
      <?php
      the_posts_pagination( array(
        'prev_text' => '‹',
        'next_text' => '›',
      ) );
      ?>
    </div>

  <?php else : ?>
    <p>No posts found.</p>
  <?php endif; ?>

</main>

<?php get_footer(); ?>
