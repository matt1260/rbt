#!/usr/bin/env python3
"""Extract and display the WordPress main page search bar."""

from wordpress_db import WordPressDBConnector
import urllib.parse

def main():
    connector = WordPressDBConnector()
    
    # Get main page content
    query = """
    SELECT post_content
    FROM wplo_posts
    WHERE ID = 851 AND post_type = 'page'
    """
    result = connector.execute_query(query, fetch='one')
    
    if not result:
        print("Main page (ID 851) not found")
        return
    
    content = result['post_content']
    
    # Find the encoded HTML section
    if '[vc_raw_html]' not in content:
        print("No [vc_raw_html] section found")
        return
    
    start = content.find('[vc_raw_html]') + len('[vc_raw_html]')
    end = content.find('[/vc_raw_html]', start)
    encoded = content[start:end]
    
    # Decode the URL-encoded content (needs double decoding)
    decoded = urllib.parse.unquote(encoded)
    decoded = urllib.parse.unquote(decoded)  # Second decode
    
    print('=== FULL DECODED HTML CONTENT ===')
    print(decoded)
    print('\n\n')
    
    # Find search bar specifically
    if 'front_search' in decoded:
        search_start = decoded.find('<table class="front_search"')
        if search_start != -1:
            search_end = decoded.find('</table>', search_start) + 8
            print('=== SEARCH BAR SECTION ===')
            print(decoded[search_start:search_end])
        else:
            print("Search bar table found but couldn't extract full markup")
    else:
        print("No 'front_search' class found in decoded content")

if __name__ == '__main__':
    main()
