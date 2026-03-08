// Bible book data extracted from the existing WordPress front page
// Each book has its RBT name translation and available chapter links

const READ_BASE = 'https://read.realbible.tech';

export const greekTestament = [
  {
    title: 'He is a Gift',
    traditional: 'Matthew',
    chapters: 28,
    linked: Array.from({ length: 28 }, (_, i) => i + 1),
  },
  {
    title: 'Hammer',
    traditional: 'Mark',
    chapters: 16,
    linked: Array.from({ length: 16 }, (_, i) => i + 1),
  },
  {
    title: 'He is Favored',
    traditional: 'John',
    chapters: 21,
    linked: Array.from({ length: 21 }, (_, i) => i + 1),
  },
  {
    title: 'Light Giver',
    traditional: 'Luke',
    chapters: 24,
    linked: Array.from({ length: 24 }, (_, i) => i + 1),
  },
  {
    title: 'The Acts of the Sent Away Ones',
    traditional: 'Acts',
    chapters: 28,
    linked: Array.from({ length: 18 }, (_, i) => i + 1),
  },
  {
    title: 'The People of Bodily Strength',
    traditional: 'Romans',
    chapters: 16,
    linked: [1, 2],
  },
  {
    title: 'First People of Young Maiden',
    traditional: '1Corinthians',
    chapters: 16,
    linked: [13],
  },
  {
    title: 'Second People of Young Maiden',
    traditional: '2Corinthians',
    chapters: 13,
    linked: [],
  },
  {
    title: 'The People of the Land of Milk',
    traditional: 'Galatians',
    chapters: 6,
    linked: [1, 2, 3, 4, 5, 6],
  },
  {
    title: 'The People of the Land of Bees',
    traditional: 'Ephesians',
    chapters: 6,
    linked: [1, 2, 3, 4, 5, 6],
  },
  {
    title: 'The People of the Horse',
    traditional: 'Philippians',
    chapters: 4,
    linked: [1],
  },
  {
    title: 'The People of the Colossal Ones',
    traditional: 'Colossians',
    chapters: 4,
    linked: [],
  },
  {
    title: 'First People of the Prayer of Victory',
    traditional: '1Thessalonians',
    chapters: 5,
    linked: [],
  },
  {
    title: 'Second People of the Prayer of Victory',
    traditional: '2Thessalonians',
    chapters: 3,
    linked: [],
  },
  {
    title: 'First Honor of God',
    traditional: '1Timothy',
    chapters: 6,
    linked: [1],
  },
  {
    title: 'Second Honor of God',
    traditional: '2Timothy',
    chapters: 4,
    linked: [],
  },
  {
    title: 'Avenged',
    traditional: 'Titus',
    chapters: 3,
    linked: [1, 2, 3],
  },
  {
    title: 'The Kisser',
    traditional: 'Philemon',
    chapters: 1,
    linked: [],
  },
  {
    title: 'Beyond Ones',
    traditional: 'Hebrews',
    chapters: 13,
    linked: [],
  },
  {
    title: 'Heel Chaser',
    traditional: 'James',
    chapters: 5,
    linked: [1, 2, 3, 4, 5],
  },
  {
    title: 'First Stone',
    traditional: '1Peter',
    chapters: 5,
    linked: [],
  },
  {
    title: 'Second Stone',
    traditional: '2Peter',
    chapters: 3,
    linked: [],
  },
  {
    title: 'First Favored',
    traditional: '1John',
    chapters: 5,
    linked: [1, 2, 3, 4, 5],
  },
  {
    title: 'Second Favored',
    traditional: '2John',
    chapters: 1,
    linked: [1],
  },
  {
    title: 'Third Favored',
    traditional: '3John',
    chapters: 1,
    linked: [1],
  },
  {
    title: 'Confessor',
    traditional: 'Jude',
    chapters: 1,
    linked: [1],
  },
  {
    title: 'The Unveiling',
    traditional: 'Revelation',
    chapters: 22,
    linked: Array.from({ length: 22 }, (_, i) => i + 1),
  },
];

export const hebrewTestament = [
  {
    title: 'Within the Head',
    traditional: 'Genesis',
    chapters: 50,
    linked: [1, 2, 3, 4, 5, 11, 15, 21, 22, 33],
    highlight: 'the Head',
  },
  {
    title: 'And A Mighty One of Names',
    traditional: 'Exodus',
    chapters: 40,
    linked: [3, 20],
    highlight: 'A Mighty One',
  },
  {
    title: 'And He is Summoning',
    traditional: 'Leviticus',
    chapters: 27,
    linked: [],
  },
  {
    title: 'And He is Aligning',
    traditional: 'Numbers',
    chapters: 36,
    linked: [],
  },
  {
    title: 'A Mighty One of the Alignments',
    traditional: 'Deuteronomy',
    chapters: 34,
    linked: [],
    highlight: 'A Mighty One',
  },
  {
    title: 'He Is Salvation',
    traditional: 'Joshua',
    chapters: 24,
    linked: [],
  },
  {
    title: 'Judges',
    traditional: 'Judges',
    chapters: 21,
    linked: [],
  },
  {
    title: 'Companion',
    traditional: 'Ruth',
    chapters: 4,
    linked: [],
    highlight: 'Companion',
  },
  {
    title: 'First Name of God',
    traditional: '1 Samuel',
    chapters: 31,
    linked: [],
  },
  {
    title: 'Second Name of God',
    traditional: '2 Samuel',
    chapters: 24,
    linked: [],
  },
  {
    title: 'First Kings',
    traditional: '1 Kings',
    chapters: 22,
    linked: [18],
  },
  {
    title: 'Second Kings',
    traditional: '2 Kings',
    chapters: 25,
    linked: [],
  },
  {
    title: 'First Alignments of the Days',
    traditional: '1 Chronicles',
    chapters: 29,
    linked: [],
  },
  {
    title: 'Second Alignments of the Days',
    traditional: '2 Chronicles',
    chapters: 36,
    linked: [],
  },
  {
    title: 'Helper',
    traditional: 'Ezra',
    chapters: 10,
    linked: [],
  },
  {
    title: 'He Is Comforted',
    traditional: 'Nehemiah',
    chapters: 13,
    linked: [],
  },
  {
    title: 'Star',
    traditional: 'Esther',
    chapters: 10,
    linked: [1],
    highlight: 'Star',
  },
  {
    title: 'Adversary',
    traditional: 'Job',
    chapters: 42,
    linked: [36, 38],
  },
  {
    title: 'Melodies',
    traditional: 'Psalms',
    chapters: 150,
    linked: [1, 8, 23, 42, 56, 82, 117, 128, 150],
  },
  {
    title: 'Parables/Comparisons',
    traditional: 'Proverbs',
    chapters: 31,
    linked: [5, 6],
  },
  {
    title: 'Alignments of the Assembler',
    traditional: 'Ecclesiastes',
    chapters: 12,
    linked: [1],
    highlight: 'the Assembler',
  },
  {
    title: 'The Song of Singers',
    traditional: 'Song of Solomon',
    chapters: 8,
    linked: [1, 2, 3, 4, 5, 6, 7, 8],
    highlight: 'The Song',
  },
  {
    title: 'He Is Liberator',
    traditional: 'Isaiah',
    chapters: 66,
    linked: [1, 9, 53],
  },
  {
    title: 'He Is Lifting Up',
    traditional: 'Jeremiah',
    chapters: 52,
    linked: [],
  },
  {
    title: 'How She Sat Desolate!',
    traditional: 'Lamentations',
    chapters: 5,
    linked: [],
  },
  {
    title: 'God Holds Strongly',
    traditional: 'Ezekiel',
    chapters: 48,
    linked: [16],
  },
  {
    title: 'God Has Judged',
    traditional: 'Daniel',
    chapters: 12,
    linked: [7],
  },
  {
    title: 'Salvation',
    traditional: 'Hosea',
    chapters: 14,
    linked: [],
  },
  {
    title: 'Being God',
    traditional: 'Joel',
    chapters: 3,
    linked: [1, 2, 3],
  },
  {
    title: 'Heavy Burdened',
    traditional: 'Amos',
    chapters: 9,
    linked: [],
  },
  {
    title: 'Slave of He Is',
    traditional: 'Obadiah',
    chapters: 1,
    linked: [],
  },
  {
    title: 'Dove',
    traditional: 'Jonah',
    chapters: 4,
    linked: [1, 2, 3, 4],
  },
  {
    title: 'Who is Like Her',
    traditional: 'Micah',
    chapters: 7,
    linked: [1],
  },
  {
    title: 'Consolation',
    traditional: 'Nahum',
    chapters: 3,
    linked: [],
  },
  {
    title: 'Embrace-Embrace',
    traditional: 'Habakkuk',
    chapters: 3,
    linked: [],
  },
  {
    title: 'He Is Concealed',
    traditional: 'Zephaniah',
    chapters: 3,
    linked: [],
  },
  {
    title: 'Festival',
    traditional: 'Haggai',
    chapters: 2,
    linked: [],
  },
  {
    title: 'He Is Remembered',
    traditional: 'Zechariah',
    chapters: 14,
    linked: [4, 5],
  },
  {
    title: 'Angel of Myself',
    traditional: 'Malachi',
    chapters: 4,
    linked: [],
  },
];

export const apocryphal = [
  {
    title: 'He Adds and Storehouse',
    traditional: 'Joseph and Aseneth',
    chapters: 29,
    linked: Array.from({ length: 29 }, (_, i) => i + 1),
    basePath: '/aseneth/',
    highlight: 'Storehouse',
  },
];

export function getChapterUrl(book, chapter) {
  if (book.basePath) {
    return `${READ_BASE}${book.basePath}?chapter=${chapter}`;
  }
  return `${READ_BASE}/?book=${encodeURIComponent(book.traditional)}&chapter=${chapter}`;
}

export const featuredQuotes = [
  {
    text: 'He has unfolded alignments of yourself; he who gives understanding is illuminating the naive ones.',
    ref: 'Psalm 119:130 RBT',
  },
  {
    text: 'For the bias of the Flesh is Death, but the bias of the Spirit, Zoe-Life and Peace.',
    ref: 'Romans 8:6 RBT',
  },
  {
    text: 'And United is making to himself a dagger, and she has twofold mouths...',
    ref: 'Judges 3:16 RBT',
  },
  {
    text: 'My people have been destroyed from lack of the Knowledge...',
    ref: 'Hosea 4:6 RBT',
  },
];

export const scienceArticles = [
  {
    title: 'The Architecture of Being: Logos as the Aonic Operator of Ratio and Flesh',
    url: 'https://www.realbible.tech/the-architecture-of-being-logos-as-the-aonic-operator-of-ratio-and-flesh/',
  },
  {
    title: 'Möbius Scripture: Biblical Hebrew as a Proto-Aonic Language of Atemporal Causality',
    url: 'https://www.realbible.tech/mobius-scripture-biblical-hebrew-as-a-proto-aonic-language-of-atemporal-causality/',
  },
  {
    title: 'The Tragedy of Chronos: How Human Language Locks Us Out of the Aion',
    url: 'https://www.realbible.tech/the-tragedy-of-chronos-how-human-language-locks-us-out-of-the-aion/',
  },
  {
    title: 'Aion vs. Chronos: A Symmetry to Time?',
    url: 'https://www.realbible.tech/a-symmetry-to-time/',
  },
  {
    title: 'The Logos-Agape Principle',
    url: 'https://www.realbible.tech/the-logos-principle/',
  },
  {
    title: 'Some Fun Equations',
    url: 'https://www.realbible.tech/some-fun-equations/',
  },
];

export const inscriptions = [
  {
    title: 'The Real Siloam Conduit Inscription',
    url: 'https://www.realbible.tech/siloam-conduit-inscription/',
    era: 'c. 8th century BCE',
  },
  {
    title: 'The Real Gezer Calendar',
    url: 'https://www.realbible.tech/the-gezer-calendar/',
    era: 'c. 10th century BCE',
  },
];

// All 71 supported languages (from SUPPORTED_LANGUAGES in translation_utils.py)
export const supportedLanguages = {
  en: 'English',
  hr: 'Hrvatski',
  sr: 'Српски',
  he: 'עברית',
  el: 'Ελληνικά',
  es: 'Español',
  fr: 'Français',
  de: 'Deutsch',
  it: 'Italiano',
  pt: 'Português',
  ru: 'Русский',
  ar: 'العربية',
  zh: '中文',
  hi: 'हिन्दी',
  pl: 'Polski',
  uk: 'Українська',
  ro: 'Română',
  nl: 'Nederlands',
  sv: 'Svenska',
  hu: 'Magyar',
  cs: 'Čeština',
  tr: 'Türkçe',
  ja: '日本語',
  ko: '한국어',
  vi: 'Tiếng Việt',
  th: 'ไทย',
  id: 'Bahasa Indonesia',
  bn: 'বাংলা',
  ur: 'اردو',
  fa: 'فارسی',
  pa: 'ਪੰਜਾਬੀ',
  mr: 'मराठी',
  ta: 'தமிழ்',
  sw: 'Kiswahili',
  ha: 'Hausa',
  yo: 'Yorùbá',
  ig: 'Igbo',
  am: 'አማርኛ',
  om: 'Afaan Oromoo',
};
