"""Display titles for the RBT front-end.

Centralizes the user-facing book title overrides so templates and views
can import from a single location.
"""

rbt_books: dict[str, str] = {
    'Genesis': 'In the Head',
    'Exodus': 'A Mighty One of Names',
    'Leviticus': 'He is Summoning',
    'Numbers': 'He is Aligning',
    'Deuteronomy': 'A Mighty One of Alignments',
    'Esther': 'Star',
    'Psalms': 'Melodies',
    'Song of Solomon': 'Song of Singers',
    'Job': 'Adversary',
    'Isaiah': 'He is Liberator',
    'Ezekiel': 'God Holds Strong',
    'John': 'He is Favored',
    'Matthew': 'He is a Gift',
    'Mark': 'Hammer',
    'Luke': 'Light Giver',
    'Acts': 'Acts of Sent Away Ones',
    'Revelation': 'Unveiling',
    'Hebrews': 'Beyond Ones',
    'Jonah': 'Dove',
    '1 John': 'First Favored',
    '2 John': 'Second Favored',
    '3 John': 'Third Favored',
    'James': 'Heel Chaser',
    'Galatians': 'People of the Land of Milk',
    'Philippians': 'People of the Horse',
    'Ephesians': 'People of the Land of Bees',
    'Colossians': 'People of Colossal Ones',
    'Titus': 'Avenged',
    '1 Timothy': 'First Honored One',
    '2 Timothy': 'Second Honored One',
}
