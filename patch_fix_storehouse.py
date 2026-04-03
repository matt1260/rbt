with open("search/views/storehouse_views.py", "r") as f:
    text = f.read()

text = text.replace("redirect('aseneth_seo_view_lang', lang_code=la, chapter=ch, permanent=True)", "redirect('aseneth_seo_view_lang', lang_code=la, chapter_num=ch, permanent=True)")
text = text.replace("redirect('aseneth_seo_view', chapter=ch, permanent=True)", "redirect('aseneth_seo_view', chapter_num=ch, permanent=True)")

text = text.replace("reverse('aseneth_seo_view_lang', kwargs={'lang_code': language, 'chapter': number})", "reverse('aseneth_seo_view_lang', kwargs={'lang_code': language, 'chapter_num': number})")
text = text.replace("reverse('aseneth_seo_view', kwargs={'chapter': number})", "reverse('aseneth_seo_view', kwargs={'chapter_num': number})")

with open("search/views/storehouse_views.py", "w") as f:
    f.write(text)

