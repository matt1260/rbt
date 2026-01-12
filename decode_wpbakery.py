#!/usr/bin/env python3
"""Decode WP Bakery Page Builder HTML content."""

import urllib.parse

# Read the URL-encoded content
with open('current_search_bar.html', 'r') as f:
    encoded = f.read().strip()

# Decode iteratively until we get clean HTML
decoded = encoded
for i in range(10):
    new_decoded = urllib.parse.unquote(decoded)
    if new_decoded == decoded:
        print(f"Stopped decoding after {i} iterations")
        break
    decoded = new_decoded
    if '<div' in decoded:
        print(f"Found HTML at iteration {i+1}")
        break

# Save the decoded HTML
with open('search_bar_decoded_clean.html', 'w', encoding='utf-8') as f:
    f.write(decoded)

print(f"\nDecoded {len(decoded)} characters")
print(f"Contains HTML tags: {'<div' in decoded}")
print("\n" + "="*60)
print("DECODED HTML:")
print("="*60)
print(decoded)
