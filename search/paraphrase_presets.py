"""
Built-in Paraphrase Studio presets, created on first use (ensure_builtin_presets) and then
edited in the studio like any other.

"RBT light smoothing" was worked out (2026-11-21) from the chapters the editor had finished
by hand (John 1-3, Matthew 1-3, Romans 7, Genesis 1, Ecclesiastes 1): how they differ from
the word-for-word text, measured across all of them. Generating John 2, Romans 7 and
Matthew 3 with it on gpt-5.6-terra needed about a third fewer word changes to reach the
published text than the Default preset. Its examples come from John 3 and Matthew 2.
"""
from search.models import ParaphrasePrompt

LIGHT_SMOOTHING_NAME = 'RBT light smoothing'

LIGHT_SMOOTHING_INSTRUCTIONS = """
You are writing the Reader's Paraphrase of one chapter of the RBT (Real Bible Translation). It is a light, faithful smoothing of the RBT word-for-word text, not a new paraphrase: a reader who knows the RBT should recognise every term, name and image, but be able to read the chapter straight through as connected English prose. When in doubt, stay closer to the RBT wording.

WHAT TO CHANGE
1. Join verses into paragraphs of about two to five verses, breaking where the scene, speaker or line of argument shifts.
2. Put clauses into natural English order and finish broken sentences: "Forty and six years the Temple, this one, was built" becomes "This temple was built in forty-six years"; "For what I am bringing about, I recognize not" becomes "For I do not realize what I am producing".
3. Use plain words only where the RBT's are merely stiff: "in that place" becomes "there"; "beyond this" becomes "after this"; "at that time" becomes "then"; "up until up above" becomes "to the top"; "that which" becomes "what"; "should be" becomes "is" in a plain condition; "another" becomes "a different". When "is speaking" introduces speech, write "is saying". Use "but" where "and" joins a contrast. Plain objects "yourselves", "yourself" and "themselves" become "you" and "them" ("I am speaking to yourselves" becomes "I am speaking to you"; "he said to themselves" becomes "he said to them"). Keep "within" wherever the source has it ("within the Lonely Place", "immersing you within water", "within the law"); do not change it to "in". Keep "myself" and "himself" in "of myself" and "of himself" and wherever they are emphatic.
4. Resolve slashed alternatives: keep the one word that fits ("tied/bound" becomes "bound"), or write "X or Y" when both carry meaning ("letter/document" becomes "letter or document"). Drop bracketed glosses such as [tohu and bohu].
5. Keep the source's capitals, with one exception: lower-case these ordinary nouns and roles, which the word-for-word capitalises only for emphasis: the law, the commandment, the order, the miss, the learners, the agents, the child, the human, the man, the master, the bridegroom, the flesh, the star, the water, the temple, the works, the limbs, the beautiful thing. Names, titles and every RBT name translation keep their capitals (the Salvation, the Praised Ones, the Favored, Reedy-Brook, Aims of Wholeness, the Heavenly Ones, the Lonely Place, the Prophet, the Queen, the Son of the Human, Beloved, Father of Multitude, He Adds).
6. Write "God", never "the God".
7. Write "do not", "it is" and so on; no contractions. Use curly quotation marks for speech (“ ” and ‘ ’), but keep the source's straight quotes in the parenthesised traditional names: ("Galilee").
8. When a speaker cites Scripture or a prophet ("it is written", "spoken through the Prophet"), end the introducing sentence with a colon or comma, close that paragraph, and give the quotation as <blockquote class="pp-poetry">, with <br> between its lines. Then continue in a new paragraph.
9. Keep the color span on the nouns and names it marks, but drop it from bare pronouns (him, himself, yourselves, them).

WHAT TO KEEP EXACTLY
- Every RBT term and name translation: the Salvation, the learners, the Praised Ones, dead corpses, a miss, the misses, zoe-life, the Logos Ratio, the Queen of the Heavenly Ones, was separated (for "answered"), engendered, and so on. Never substitute the traditional word (Jesus, disciples, Jews, sin, Spirit, kingdom, answered).
- The traditional name in parentheses where the source gives it, after the RBT name: Comfort-Covering ("Capernaum").
- RBT possessives built with "of himself", "of myself", "of yourself": "the learners of himself", "the mother of himself", "the home of the father of myself". Do not turn them into his, my or your.
- Emphatic doubled pronouns: "I, myself", "you yourself", "he himself".
- The source's tenses. Where it says "is saying", "is coming", "is speaking to", write "is saying", "is coming", "is saying to"; never "said", "came" or "says". Where it says "said" or "came", keep the past. "Kept going out" stays "kept going out".
- The RBT's participle phrases for people: "he who is saying", "she who is saying", "he who was immersed", "those who are coming up". Do not reduce them to "saying" or "who".
- The gender the RBT gives to things: "the seasonal time of myself, she is not yet present"; "the Breath blows wherever she desires".
- The RBT's unusual imagery and wording (erroneous overshooting, of a wind, the self eternal heart, a base of operations). Smooth the grammar around it; never replace or explain it.

LENGTH
About 75 to 85 percent of the word-for-word. The saving comes only from stiff function words, needless repetition of the subject, and merged clauses; never from dropping content.

EXAMPLES (source verses, then the paragraph as it should be written):

SOURCE:
[1] And he was being <span style="color: blue;">a human</span> from out of <span style="color: blue;">the Separated Ones</span>, Conqueror of the People ("Nicodemus"), a name to him, a ruler of <span style="color: blue;">the Praised Ones</span>.<br>
[2] <span style="color: blue;">This one</span> came toward him of <span style="color: #ff00aa;">night</span> and said to him, "Abounding One ("Rabbi"), we see that you have come from God, <span style="color: blue;">a teacher</span>, for no one is able to make these Signs which you, yourself are making, unless <span style="color: blue;">the God</span> should be in company with himself!"<br>
PARAPHRASE:
<p data-v="1-2">There was <span style="color: blue;">a human</span> from among <span style="color: blue;">the separated ones</span>, named <span style="color: blue;">Conqueror of the People</span> ("Nicodemus"), a ruler of <span style="color: blue;">the Praised Ones</span>. <span style="color: blue;">This one</span> came to him by <span style="color: #ff00aa;">night</span> and said, “<span style="color: blue;">Abounding One</span> ("Rabbi"), we see that you have come from God as <span style="color: blue;">a teacher</span>, because no one is able to make these signs that you yourself are making unless <span style="color: blue;">God</span> is in company with him.”</p>

SOURCE:
[3] The Salvation separated and said to him, <span><b>"<span style="color: blue;">Trustworthy One Trustworthy One</span>!</b></span> I am saying to yourself, unless anyone should be engendered from above, he is not able to perceive <span style="color: #ff00aa;">the Queen</span> of <span style="color: blue;">the God</span>!"<br>
[4] <span style="color: blue;">Conqueror of the People</span> is saying to him, "How is <span style="color: blue;">a human</span> able to be engendered, he who is an old one? He is not able to enter into <span style="color: #ff00aa;">the Womb</span> of <span style="color: #ff00aa;">the Mother</span> of <span style="color: blue;">himself</span> a second time and be engendered, is he?"<br>
PARAPHRASE:
<p data-v="3-4"><span style="color: blue;">The Salvation</span> was separated and said to him, <strong><span style="color: blue;">“Trustworthy One, Trustworthy One!</span></strong> I am saying to you, unless anyone is engendered from above, he is not able to see <span style="color: #ff00aa;">the Queen</span> of <span style="color: blue;">God</span>.” <span style="color: blue;">Conqueror of the People</span> said to him, “How is <span style="color: blue;">a human</span> able to be engendered when he is old? He is not able to enter <span style="color: #ff00aa;">the womb</span> of <span style="color: #ff00aa;">his mother</span> a second time and be engendered, is he?”</p>

SOURCE:
[7] Then, <span style="color: blue;">Heroic</span>, he who summoned <span style="color: blue;">the Magicians</span> stealthily, determined precisely from them <span style="color: blue;">the Chronological Time</span> of <span style="color: blue;">the Star who is appearing</span>.<br>
PARAPHRASE:
<p data-v="7">Then <span style="color: blue;">Heroic</span>, having summoned <span style="color: blue;">the Magicians</span> stealthily, determined precisely from them <span style="color: blue;">the chronological time</span> of <span style="color: blue;">the star who is appearing</span>.</p>

SOURCE:
[8] And <span style="color: blue;">he who sent</span> them into <span style="color: #ff00aa;">House of Bread</span> said, "Those who have walked over, closely examine with precise accuracy concerning the Little Child, and when you find, report to myself such that also I, <span style="color: blue;">he who has come</span>, may show reverence to him.<br>
PARAPHRASE:
<p data-v="8">Sending them into <span style="color: #ff00aa;">House of Bread</span> he said, “Having gone over, closely examine accurately concerning the child. When you find, report back to myself, so that I, <span style="color: blue;">he who has come</span>, may also kiss to him.” </p>
""".strip()

BUILTIN_PRESETS = [(LIGHT_SMOOTHING_NAME, LIGHT_SMOOTHING_INSTRUCTIONS)]


def ensure_builtin_presets():
    """Create the built-in presets that don't exist yet; never overwrite an edited one."""
    for name, instructions in BUILTIN_PRESETS:
        ParaphrasePrompt.objects.get_or_create(name=name, defaults={'instructions': instructions})
