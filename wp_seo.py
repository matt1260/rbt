import sys

seo_code = """
// RBT Custom SEO hooks for hreflang and dynamic translated tagging
function rbt_add_hreflang_tags() {
    if (is_singular() || is_front_page() || is_home()) {
        $languages = array('en', 'es', 'fr', 'de', 'pt', 'it', 'nl', 'ru', 'zh', 'ja', 'ko', 'ar', 'hi', 'bn', 'ur', 'vi', 'tr', 'ta', 'te', 'th', 'sw', 'sv', 'pl', 'fa', 'uk');
        
        $current_url = explode('?', 'https://' . $_SERVER["HTTP_HOST"] . $_SERVER["REQUEST_URI"])[0];
        $base_url = preg_replace('/https:\/\/[^\/]+\/[a-z]{2}\//', 'https://' . $_SERVER["HTTP_HOST"] . '/', $current_url);
        
        echo '<link rel="alternate" href="' . esc_url($base_url) . '" hreflang="x-default" />' . "\\n";
        echo '<link rel="alternate" href="' . esc_url($base_url) . '" hreflang="en" />' . "\\n";
        
        foreach($languages as $lang) {
            if ($lang !== 'en') {
                $lang_url = str_replace(home_url('/'), home_url('/' . $lang . '/'), $base_url);
                echo '<link rel="alternate" href="' . esc_url($lang_url) . '" hreflang="' . esc_attr($lang) . '" />' . "\\n";
            }
        }
    }
}
add_action('wp_head', 'rbt_add_hreflang_tags', 1);

function rbt_dynamic_meta_description() {
    if (is_singular()) {
        global $post;
        $excerpt = wp_strip_all_tags($post->post_content);
        $excerpt = substr($excerpt, 0, 160);
        echo '<meta name="description" content="' . esc_attr($excerpt) . '..." />' . "\\n";
    }
}
add_action('wp_head', 'rbt_dynamic_meta_description', 2);
"""

try:
    with open("neve-child/functions.php", "a") as f:
        f.write(seo_code)
    print("Success")
except Exception as e:
    print("Error:", e)
