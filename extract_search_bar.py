#!/usr/bin/env python3
"""Extract search bar from WordPress main page and save to file."""

from wordpress_db import WordPressDBConnector
import urllib.parse
import base64

connector = WordPressDBConnector()

# Get main page content
query = """
SELECT post_content
FROM wplo_posts
WHERE ID = 851 AND post_type = 'page'
"""
result = connector.execute_query(query, fetch='one')

if not result:
    print("Main page not found")
    exit(1)

content = result['post_content']

# Find the encoded HTML section
if '[vc_raw_html]' not in content:
    print("No [vc_raw_html] section found")
    exit(1)

start = content.find('[vc_raw_html]') + len('[vc_raw_html]')
end = content.find('[/vc_raw_html]', start)
encoded = content[start:end]

# Try different decoding strategies
decoded = encoded

# Try URL decode multiple times
for i in range(5):
    try:
        new_decoded = urllib.parse.unquote(decoded)
        if new_decoded == decoded:
            break  # No more changes
        decoded = new_decoded
    except Exception as e:
        print(f"URL decode failed at iteration {i}: {e}")
        break

# Save to file
with open('current_search_bar.html', 'w') as f:
    f.write(decoded)

print(f"Saved {len(decoded)} characters to current_search_bar.html")

# Find search bar section
if 'front_search' in decoded:
    search_start = decoded.find('<table class="front_search"')
    if search_start != -1:
        # Find first closing </table>
        search_end = decoded.find('</table>', search_start) + 8
        search_bar = decoded[search_start:search_end]
        
        with open('desktop_search_bar.html', 'w') as f:
            f.write(search_bar)
        
        print(f"\nExtracted desktop search bar ({len(search_bar)} chars)")
        print("\nPreview:")
        print(search_bar[:500])
else:
    print("\nWarning: 'front_search' not found in decoded content")
    print("First 500 chars:", decoded[:500])
