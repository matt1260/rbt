import psycopg2
import json
import os

# PostgreSQL database URL (set in environment variable)
# export DATABASE_URL="postgres://matt:Lamentations318@localhost:5432/rbt"
DATABASE_URL = os.environ.get('DATABASE_URL')  

def load_json():
    with open('interlinear_english.json', 'r', encoding='utf-8') as file:
        json_string = file.read()

    json_string = json_string.replace("'", '"')
    if json_string[0] == '"' and json_string[-1] == '"':
        json_string = json_string[1:-1]
    json_string = json_string.replace("\\", "")

    replacements = json.loads(json_string)
    return replacements

replacements = load_json()

def replace_words(strongs, lemma, english):
    # Check if any of the conditions match and replace english if so
    for condition, replacement in replacements.items():
        if strongs == condition or lemma == condition:
            english = replacement
            break  # Exit loop after first match
    return english

# Connect to PostgreSQL
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

replacements_count = 0

try:
    # Retrieve all rows from the 'strongs_greek' table
    cur.execute("SELECT strongs, lemma, english FROM rbt_greek.strongs_greek")
    rows = cur.fetchall()

    # Iterate over the rows, apply replace_words function, and update 'english' column
    for strongs, lemma, english in rows:
        new_english = replace_words(strongs, lemma, english)

        # Check if replacement occurred and print it
        if new_english != english:
            replacements_count += 1
            print(f"Replaced '{english}' with '{new_english}' for strongs='{strongs}', lemma='{lemma}'")

            # Update the 'english' column with the new value
            cur.execute(
                "UPDATE rbt_greek.strongs_greek SET english = %s WHERE strongs = %s AND lemma = %s",
                (new_english, strongs, lemma)
            )

    # Commit the changes
    conn.commit()
    print(f"Replacement completed successfully. Total replacements: {replacements_count}")

except psycopg2.Error as e:
    print("Error executing PostgreSQL query:", e)
    conn.rollback()

finally:
    # Close the database connection
    cur.close()
    conn.close()
