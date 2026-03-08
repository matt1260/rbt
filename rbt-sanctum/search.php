<?php
/**
 * Search results template
 *
 * @package RBT_Sanctum
 */

get_header();
?>

<main class="sanctum-wp-content">

  <h1>Search Results for: <em>"<?php echo get_search_query(); ?>"</em></h1>

  <?php if ( have_posts() ) : ?>
    <ul class="sanctum-wp-post-list">
      <?php while ( have_posts() ) : the_post(); ?>
        <li class="sanctum-wp-post-item">
          <h2><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h2>
          <div class="sanctum-wp-post-excerpt"><?php the_excerpt(); ?></div>
          <a href="<?php the_permalink(); ?>" class="sanctum-wp-read-more">Read More →</a>
        </li>
      <?php endwhile; ?>
    </ul>

    <div class="sanctum-wp-pagination">
      <?php the_posts_pagination( array( 'prev_text' => '‹', 'next_text' => '›' ) ); ?>
    </div>
  <?php else : ?>
    <p>No results found. Try a different search term.</p>
  <?php endif; ?>

</main>

<?php get_footer(); ?>
