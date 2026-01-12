#!/usr/bin/env python3
import urllib.parse

with open('current_search_bar.html', 'r') as f:
    encoded = f.read()

# Multi-pass URL decode
decoded = encoded
for i in range(5):
    new_decoded = urllib.parse.unquote(decoded)
    if new_decoded == decoded or '<div' in decoded:
        break
    decoded = new_decoded

# Save
with open('search_bar_final.html', 'w') as f:
    f.write(decoded)

print(f"Decoded: {len(decoded)} chars")

# Extract desktop search bar
if 'front_search' in decoded:
    start = decoded.find('<table class="front_search"')
    end = decoded.find('</table>', start) + 8
    search_bar = decoded[start:end]
    
    with open('desktop_search_only.html', 'w') as f:
        f.write(search_bar)
    
    print("\nDesktop search bar:")
    print(search_bar)
else:
    print("\nFirst 2000 chars:")
    print(decoded[:2000])
