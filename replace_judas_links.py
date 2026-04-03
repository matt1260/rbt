import re

with open("search/templates/judas.html", "r") as f:
    content = f.read()

old_link_pattern = r"{% for num in codex_range %}\s*{% if num == codex_num %}\s*<span class=\"sanctum-chapter-link\">{{ num }}</span>\s*{% else %}\s*<a class=\"sanctum-chapter-link\" href=\"\?codex={{ num }}{% if panel %}&panel={{ panel }}{% endif %}{% if current_language != 'en' %}&lang={{ current_language }}{% endif %}\">{{ num }}</a>\s*{% endif %}\s*{% endfor %}"

new_link = """{% for num in codex_range %}
              {% if num == codex_num %}
                  <span class="sanctum-chapter-link">{{ num }}</span>
              {% else %}
                  {% if current_language != 'en' %}
                      {% if panel %}
                          <a class="sanctum-chapter-link" href="{% url 'judas_seo_view_panel_lang' lang_code=current_language codex_num=num panel_code=panel %}">{{ num }}</a>
                      {% else %}
                          <a class="sanctum-chapter-import re

with open("search/templatesg' lang_code=    content = f.read()

old_link_pattern = r"{% fo  
old_link_pattern = r en
new_link = """{% for num in codex_range %}
              {% if num == codex_num %}
                  <span class="sanctum-chapter-link">{{ num }}</span>
              {% else %}
                  {% if current_language != 'en' %}
                      {% if panel %}
                          <a class="sanctum-chapter-link" href="{% url 'judas_seo_view_panel_lang' >
               {% if num == codex_num %}
                     <span class="sanctumnd              {% else %}
                  {% if current_language !=ne                  {% ifop                      udas.html", "w") as f:
    f.w        tent)

print("Done")
