<?php
/**
 * Footer template — Sanctum-styled footer for inner pages
 *
 * @package RBT_Sanctum
 */

if ( ! defined( 'ABSPATH' ) ) exit;

$lang       = rbt_sanctum_detect_lang();
$paypal_url = 'https://www.paypal.com/donate/?hosted_button_id=6LHHSLKJCY4RY';

$languages = rbt_sanctum_get_languages();
?>

<footer class="sanctum-wp-footer">
  <div class="sanctum-wp-footer-logo">Real Bible Translation</div>

  <div class="sanctum-wp-footer-grid">
    <div class="sanctum-wp-footer-section">
      <h4>About</h4>
      <ul class="sanctum-wp-footer-nav">
        <li><a href="https://www.realbible.tech/about/">About RBT</a></li>
        <li><a href="https://www.realbible.tech/methodology/">Methodology</a></li>
        <li><a href="https://www.realbible.tech/copyrights/">Copyrights</a></li>
      </ul>
    </div>
    <div class="sanctum-wp-footer-section">
      <h4>Resources</h4>
      <ul class="sanctum-wp-footer-nav">
        <li><a href="https://www.realbible.tech/let-there-be-science/">Science</a></li>
        <li><a href="https://read.realbible.tech/statistics/">Statistics</a></li>
        <li><a href="https://www.realbible.tech/notes/">Notes</a></li>
      </ul>
    </div>
    <div class="sanctum-wp-footer-section">
      <h4>Quick Links</h4>
      <ul class="sanctum-wp-footer-nav">
        <li><a href="https://www.realbible.tech/">Home</a></li>
        <li><a href="https://read.realbible.tech/search/">Search</a></li>
        <li><a href="https://read.realbible.tech/updates/">Updates</a></li>
      </ul>
    </div>
    <div class="sanctum-wp-footer-section" id="support-this-work">
      <h4>Support this Work</h4>
      <ul class="sanctum-wp-footer-nav">
        <li><a href="https://www.paypal.com/donate/?hosted_button_id=6LHHSLKJCY4RY" target="_blank" rel="noopener">Donate via PayPal</a></li>
        <li><a href="https://mempool.space/address/bc1qcwsz2yen5f9xy7dyxma3f4wrmrck7htgwnj6al" target="_blank" rel="noopener">Donate Crypto (BTC)</a></li>
        <li><a href="https://x.com/intent/tweet?hashtags=LetMyPeopleGo&text=Reading+the+Real+Bible+Translation+Project" target="_blank" rel="noopener">Share on X #LetMyPeopleGo</a></li>
      </ul>
    </div>
  </div>

  <!-- Language grid -->
  <div class="sanctum-wp-footer-languages">
    <div class="sanctum-wp-footer-languages-title">Available Languages</div>
    <div class="sanctum-wp-footer-languages-grid">
      <?php foreach ( $languages as $code => $name ) :
        $url   = ( $code === 'en' ) ? home_url( '/' ) : home_url( '/' . $code . '/' );
        $class = ( $code === $lang ) ? 'sanctum-wp-footer-lang-btn active' : 'sanctum-wp-footer-lang-btn';
      ?>
        <a href="<?php echo esc_url( $url ); ?>" class="<?php echo esc_attr( $class ); ?>"><?php echo esc_html( $name ); ?></a>
      <?php endforeach; ?>
    </div>
  </div>

  <div class="sanctum-wp-footer-bottom">
    <a href="<?php echo esc_url( $paypal_url ); ?>">Donate</a>
    <span>·</span>
    <span>#LetMyPeopleGo</span>
    <span>·</span>
    <span>&copy; <?php echo date( 'Y' ); ?> Real Bible Translation Project</span>
  </div>
</footer>

<?php wp_footer(); ?>
</body>
</html>
