"""
Lexicon Query API

Python interface to the CATSS Hebrew-Greek lexicon with Strong's integration.
Requires: psycopg (pip install psycopg[binary])

Primary Use Case (Interlinear):
    from lexicon import Lexicon
    
    lex = Lexicon()
    
    # Get LXX translations for a Strong's number
    for heb, grk, freq, pct in lex.strongs_to_greek("H3068"):
        print(f"{heb} → {grk}: {freq} ({pct}%)")
    # Output: יהוה → κυριοσ: 5509 (76.3%)

Additional Methods:
    lex.hebrew_to_greek("אמר")      # Stem → Greek translations
    lex.greek_to_hebrew("κυριοσ")   # Greek → Hebrew stems  
    lex.get_pos("מלכ")              # Get POS classification
    lex.stem_to_lemma("יאמר")       # CATSS stem → ETCBC lemma
    lex.get_strongs("יהוה")         # Lemma → Strong's number
"""

from typing import Optional
import psycopg


class Lexicon:
    """Interface to the CATSS Hebrew-Greek lexicon database."""
    
    def __init__(self, dbname: str = "rbt", user: str = "matt"):
        self.conninfo = f"dbname={dbname} user={user}"
    
    def _query(self, sql: str, params: tuple = ()) -> list:
        """Execute a query and return results."""
        with psycopg.connect(self.conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO catss")
                cur.execute(sql, params)
                return cur.fetchall()
    
    # =========================================================================
    # PRIMARY API: Strong's Integration (for interlinear use)
    # =========================================================================
    
    def strongs_to_greek(
        self,
        strongs: str,
        limit: int = 20,
        min_freq: int = 1
    ) -> list[tuple[str, str, int, float]]:
        """
        Get Greek translations for a Strong's number.
        
        This is the PRIMARY lookup method for interlinear use.
        
        Args:
            strongs: Strong's number (e.g., "H3068" or "3068")
            limit: Maximum results to return
            min_freq: Minimum co-occurrence frequency
        
        Returns:
            List of (hebrew_lemma, greek_lemma, frequency, proportion_pct) tuples
        
        Example:
            >>> lex.strongs_to_greek("H3068")
            [('יהוה', 'κυριοσ', 5509, 76.3), ('יהוה', 'θεοσ', 247, 3.4), ...]
        """
        # Normalize: ensure H prefix
        if not strongs.startswith('H'):
            strongs = 'H' + strongs
        
        return self._query("""
            SELECT hebrew_lemma, greek_lemma, frequency, proportion_pct
            FROM strongs_lxx_profile
            WHERE strongs = %s AND frequency >= %s
            ORDER BY frequency DESC
            LIMIT %s
        """, (strongs, min_freq, limit))
    
    def get_strongs(self, lemma: str) -> Optional[str]:
        """
        Get Strong's number for a Hebrew lemma.
        
        Args:
            lemma: Hebrew lemma (ETCBC format)
        
        Returns:
            Strong's number (e.g., "3068") or None
        """
        result = self._query("""
            SELECT strongs FROM hebrew_lemma_strongs WHERE hebrew_lemma = %s
        """, (lemma,))
        return result[0][0] if result else None
    
    def stem_to_lemma(self, stem: str) -> Optional[str]:
        """
        Get ETCBC lemma for a CATSS stem.
        
        Args:
            stem: CATSS stem
        
        Returns:
            ETCBC lemma or None
        """
        result = self._query("""
            SELECT lemma FROM hebrew_stem_to_lemma WHERE stem = %s
        """, (stem,))
        return result[0][0] if result else None
    
    # =========================================================================
    # SECONDARY API: Direct stem/form lookups
    # =========================================================================
    
    def hebrew_to_greek(
        self, 
        stem: str, 
        limit: int = 20,
        min_freq: int = 1
    ) -> list[tuple[str, int]]:
        """
        Get Greek translations for a Hebrew stem.
        
        Args:
            stem: Hebrew stem (e.g., "אמר")
            limit: Maximum results to return
            min_freq: Minimum co-occurrence frequency
        
        Returns:
            List of (greek_lemma, frequency) tuples, sorted by frequency
        """
        return self._query("""
            SELECT greek_lemma, freq
            FROM stem_greek_lemma_cooccurrence
            WHERE hebrew_stem = %s AND freq >= %s
            ORDER BY freq DESC
            LIMIT %s
        """, (stem, min_freq, limit))
    
    def greek_to_hebrew(
        self, 
        lemma: str, 
        limit: int = 20,
        min_freq: int = 1
    ) -> list[tuple[str, int]]:
        """
        Get Hebrew stems for a Greek lemma.
        
        Args:
            lemma: Greek lemma (normalized, e.g., "λεγω" or "κυριοσ")
            limit: Maximum results to return
            min_freq: Minimum co-occurrence frequency
        
        Returns:
            List of (hebrew_stem, frequency) tuples, sorted by frequency
        """
        return self._query("""
            SELECT hebrew_stem, freq
            FROM stem_greek_lemma_cooccurrence
            WHERE greek_lemma = %s AND freq >= %s
            ORDER BY freq DESC
            LIMIT %s
        """, (lemma, min_freq, limit))
    
    def get_pos(self, stem: str) -> Optional[str]:
        """
        Get part-of-speech for a Hebrew stem.
        
        Args:
            stem: Hebrew stem
        
        Returns:
            POS tag ('noun', 'verb', 'proper', 'pronoun', 'demonstrative')
            or None if not found
        """
        result = self._query("""
            SELECT pos FROM hebrew_stem_class WHERE stem = %s
        """, (stem,))
        return result[0][0] if result else None
    
    def get_lemma(self, form: str) -> Optional[str]:
        """
        Get dictionary lemma for a Greek form.
        
        Args:
            form: Normalized Greek form (lowercase, no diacritics)
        
        Returns:
            Lemma or None if not found
        """
        result = self._query("""
            SELECT lemma FROM greek_lemma WHERE form = %s
        """, (form,))
        return result[0][0] if result else None
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def search_hebrew(
        self, 
        pattern: str, 
        pos: Optional[str] = None,
        limit: int = 50
    ) -> list[tuple[str, str]]:
        """
        Search Hebrew stems by pattern.
        
        Args:
            pattern: SQL LIKE pattern (e.g., "מל%" for stems starting with מל)
            pos: Optional POS filter ('noun', 'verb', etc.)
            limit: Maximum results
        
        Returns:
            List of (stem, pos) tuples
        """
        if pos:
            return self._query("""
                SELECT stem, pos FROM hebrew_stem_class
                WHERE stem LIKE %s AND pos = %s
                ORDER BY stem LIMIT %s
            """, (pattern, pos, limit))
        else:
            return self._query("""
                SELECT stem, pos FROM hebrew_stem_class
                WHERE stem LIKE %s
                ORDER BY stem LIMIT %s
            """, (pattern, limit))
    
    def alignment_for_verse(
        self, 
        book: str, 
        chapter: int, 
        verse: int
    ) -> list[tuple[str, str, str]]:
        """
        Get all alignment groups for a verse.
        
        Args:
            book: Book code (e.g., "GEN", "EXO")
            chapter: Chapter number
            verse: Verse number
        
        Returns:
            List of (group_id, hebrew_surface, greek_surface) tuples
        """
        pattern = f"{book}.{chapter}.{verse}.%"
        return self._query("""
            SELECT 
                ag.group_id,
                ht.surface AS hebrew,
                gt.surface AS greek
            FROM alignment_group ag
            JOIN hebrew_token ht ON ht.group_id = ag.group_id
            JOIN greek_token gt ON gt.group_id = ag.group_id
            WHERE ag.group_id LIKE %s
            ORDER BY ag.group_id, ht.token_order
        """, (pattern,))
    
    def top_correspondences(
        self, 
        pos: Optional[str] = None, 
        limit: int = 50
    ) -> list[tuple[str, str, str, int]]:
        """
        Get top Hebrew-Greek correspondences.
        
        Args:
            pos: Optional POS filter ('noun', 'verb', 'proper', etc.)
            limit: Maximum results
        
        Returns:
            List of (hebrew_stem, hebrew_pos, greek_lemma, freq) tuples
        """
        if pos:
            return self._query("""
                SELECT hebrew_stem, hebrew_pos, greek_lemma, freq
                FROM stem_greek_cooccurrence_enriched
                WHERE hebrew_pos = %s
                ORDER BY freq DESC
                LIMIT %s
            """, (pos, limit))
        else:
            return self._query("""
                SELECT hebrew_stem, hebrew_pos, greek_lemma, freq
                FROM stem_greek_cooccurrence_enriched
                ORDER BY freq DESC
                LIMIT %s
            """, (limit,))


# =============================================================================
# COMMAND-LINE INTERFACE
# =============================================================================

if __name__ == "__main__":
    import sys
    
    lex = Lexicon()
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python lexicon.py --strongs H3068   # Primary: Strong's → LXX")
        print("  python lexicon.py --greek κυριοσ   # Greek → Hebrew stems")
        print("  python lexicon.py אמר              # Hebrew stem info")
        sys.exit(1)
    
    if sys.argv[1] == "--strongs" and len(sys.argv) >= 3:
        strongs = sys.argv[2]
        print(f"LXX translations for {strongs}:")
        for heb, grk, freq, pct in lex.strongs_to_greek(strongs):
            print(f"  {heb} → {grk}: {freq} ({pct}%)")
    
    elif sys.argv[1] == "--greek" and len(sys.argv) >= 3:
        lemma = sys.argv[2]
        print(f"Hebrew stems for '{lemma}':")
        for stem, freq in lex.greek_to_hebrew(lemma):
            print(f"  {stem}: {freq}")
    
    else:
        stem = sys.argv[1]
        lemma = lex.stem_to_lemma(stem)
        strongs = lex.get_strongs(lemma) if lemma else None
        pos = lex.get_pos(stem)
        
        print(f"Hebrew stem: {stem}")
        print(f"ETCBC lemma: {lemma or 'unknown'}")
        print(f"Strong's: H{strongs}" if strongs else "Strong's: unknown")
        print(f"POS: {pos or 'unknown'}")
        print(f"Greek translations:")
        for grk, freq in lex.hebrew_to_greek(stem, limit=10):
            print(f"  {grk}: {freq}")
