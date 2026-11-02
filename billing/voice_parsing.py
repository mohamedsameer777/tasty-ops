"""
Parses spoken/typed order text into structured line items matched against a
shop's actual menu.

    "two chicken momo one veg momo fried 3 french fries"
        -> 2 x Chicken Momo, 1 x Veg Momo (fried), 3 x French Fries

Used by OrderViewSet.voice_add - see views.py.

Why this is more than "split on 'and'":
  * Speech-to-text almost never inserts commas or the word "and" between
    items. It just gives "two chicken momo one veg momo". So the text is also
    split wherever a NEW QUANTITY starts ("two ... one ... 3 ...").
  * Quantities can come before ("two momo") or after ("momo two", "momo x2").
  * Speech engines mishear food words ("burgar", "mamos", "mo mo", "chiken").
    Words are normalised through an alias list, adjacent fragments are glued
    back together, and anything close to a word in THIS shop's menu is snapped
    to it - so it works for any shop's menu, not just one hard-coded menu.
  * If two menu items match equally well (e.g. "chicken burger" when you sell
    both a Chicken Patty Burger and a Fried Chicken Burger) the parser does
    NOT guess. It returns the best candidates as `suggestions` so the screen
    can offer one-tap buttons instead of silently adding the wrong dish.
"""
import re
from difflib import SequenceMatcher, get_close_matches

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

# Minimum score for a menu match to be trusted at all.
MATCH_THRESHOLD = 0.5
# If the runner-up is within this distance of the winner, it is a tie -> ask.
AMBIGUITY_MARGIN = 0.06
# Anything above this is almost certainly a mis-heard number -> ask.
MAX_QUANTITY = 50
MAX_SUGGESTIONS = 3

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

# Number words that are safe to treat as "a new item starts here".
STRONG_NUMBERS = {
    'one': 1, 'single': 1, 'won': 1, 'wan': 1,
    'two': 2, 'couple': 2, 'pair': 2,
    'three': 3, 'few': 3,
    'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'dozen': 12,
    'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
    'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'half-dozen': 6, 'halfdozen': 6,
    # Hindi / Tamil numbers, written the way a speech engine usually spells them
    'ek': 1, 'onnu': 1, 'rendu': 2, 'teen': 3, 'moonu': 3, 'munu': 3,
    'char': 4, 'naalu': 4, 'panch': 5, 'paanch': 5, 'anju': 5,
}

# Homophones / ambiguous words. Only counted as a quantity at the very start
# of an item, or mid-sentence when what follows clearly matches a menu item.
WEAK_NUMBERS = {
    'a': 1, 'an': 1,
    'to': 2, 'too': 2, 'tu': 2, 'do': 2,
    'for': 4, 'fore': 4, 'ate': 8, 'tree': 3,
}

# "6 pcs", "100 grm" - a size, not a quantity.
SIZE_WORDS = {'pcs', 'pc', 'piece', 'pieces', 'pic', 'pics', 'grm', 'gram', 'grams', 'gm', 'gms', 'g'}

# Whole segment means "forget that".
CANCEL_WORDS = {'cancel', 'undo', 'nevermind', 'never mind', 'ignore that', 'ignore'}

FRIED_WORDS = {'fried', 'fry', 'crispy'}
CHEESE_WORDS = {'cheese', 'cheesy'}
PARCEL_WORDS = {
    'parcel', 'takeaway', 'take-away', 'take', 'packing', 'pack',
    'togo', 'to-go', 'packed', 'packet',
}
NEGATION_WORDS = {'no', 'without', 'not', "don't", 'dont', 'skip'}

# Words around an order that carry no menu information.
FILLER_WORDS = {
    'give', 'me', 'please', 'i', 'want', 'need', 'order', 'get', 'add',
    'the', 'a', 'an', 'some', 'of', 'plate', 'plates', 'item', 'items', 'with',
    'for', 'to', 'too', 'in', 'on', 'my', 'it', 'this', 'that', 'these', 'those',
    'just', 'only', 'away', 'go', 'all', 'everything', 'both', 'every', 'sab',
    'okay', 'ok', 'um', 'uh', 'can', 'you', 'also', 'and',
} | SIZE_WORDS

# Stripped from the very start of a segment ("give me two burgers").
LEADING_FILLERS = {
    'give', 'me', 'please', 'i', 'want', 'need', 'order', 'get', 'add',
    'the', 'okay', 'ok', 'um', 'uh', 'can', 'you', 'also', 'just',
}

MODIFIER_FILLER = {'extra', 'more'}

# Common mis-hearings / spellings -> one canonical word. Applied to BOTH the
# spoken words and the menu names, so "lollipop" matches a menu that spells it
# "Lolipop". Add more here as you notice them.
ALIASES = {
    'burgar': 'burger', 'burgur': 'burger', 'berger': 'burger', 'burga': 'burger',
    'mamo': 'momo', 'mommo': 'momo', 'mumo': 'momo', 'momoz': 'momo',
    'mamos': 'momo', 'mom': 'momo', 'momoes': 'momo', 'momoe': 'momo',
    'chiken': 'chicken', 'chikken': 'chicken', 'checken': 'chicken',
    'chickan': 'chicken', 'chicke': 'chicken', 'chikan': 'chicken',
    'panner': 'paneer', 'panir': 'paneer', 'paner': 'paneer', 'panear': 'paneer',
    'vej': 'veg', 'veggie': 'veg', 'veggy': 'veg', 'vegetable': 'veg',
    'vedge': 'veg', 'vege': 'veg', 'weg': 'veg',
    'perry': 'peri', 'pari': 'peri', 'perri': 'peri',
    'tika': 'tikka', 'tikkah': 'tikka',
    'lollipop': 'lolipop', 'lollypop': 'lolipop', 'lolypop': 'lolipop', 'lolli': 'lolipop',
    'samosha': 'samosa', 'samoosa': 'samosa',
    'catlet': 'cutlet', 'cutlass': 'cutlet', 'cutlets': 'cutlet',
    'chese': 'cheese', 'cheez': 'cheese', 'chees': 'cheese', 'cheeze': 'cheese', 'chiz': 'cheese',
    'prawan': 'prawn', 'prawns': 'prawn',
    'role': 'roll', 'rolls': 'roll',
    'pop-corn': 'popcorn',
    'parsal': 'parcel', 'parsel': 'parcel', 'parcell': 'parcel', 'parcels': 'parcel',
    'frys': 'fries', 'fryes': 'fries',
}

# Already in the menu-name form; never singularize.
NO_SINGULARIZE = {'fries', 'lays', 'pasta', 'sauce'}

_NUMBER_WORDS = set(STRONG_NUMBERS) | set(WEAK_NUMBERS)
_NON_NAME = (
    FILLER_WORDS | LEADING_FILLERS | NEGATION_WORDS | FRIED_WORDS | CHEESE_WORDS
    | PARCEL_WORDS | MODIFIER_FILLER | SIZE_WORDS | _NUMBER_WORDS
)

_SPLIT_RE = re.compile(r"[,;\n]+|\b(?:and|also|plus|then|next|aur)\b")
_GLOBAL_PARCEL_RE = re.compile(
    r"\b(?:all|everything|both|every|sab|total)\s+(?:" +
    "|".join(sorted((re.escape(w) for w in PARCEL_WORDS | {'parcel', 'parcels'}), key=len, reverse=True)) +
    r")\b"
)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _singularize(word):
    """Tiny, food-menu-appropriate plural stripper: burgers -> burger, momos -> momo."""
    if word in NO_SINGULARIZE:
        return word
    if len(word) > 3 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 4 and word.endswith('s') and not word.endswith('ss'):
        return word[:-1]
    return word


def _canon(word):
    word = ALIASES.get(word, word)
    word = _singularize(word)
    return ALIASES.get(word, word)


def _number_value(tok):
    """Value of a strong number token (digit, word, or an explicit '#2' from 'x2'), else None."""
    if tok.startswith('#') and tok[1:].isdigit():
        return int(tok[1:])
    if tok.isdigit():
        return int(tok)
    return STRONG_NUMBERS.get(tok)


def _is_name_token(tok):
    return tok not in _NON_NAME and _number_value(tok) is None


def _tokenize(text):
    return re.findall(r"#\d+|[a-z0-9_]+(?:[-'][a-z0-9_]+)*", text)


def _protect(text):
    """Shield 'and' and digits that are part of a dish name ('Fish and Chips', 'Chicken 65')."""
    text = re.sub(r'\b(\d+)\b', r'_\1_', text)
    return re.sub(r'\band\b', '_and_', text)


# --------------------------------------------------------------------------
# Menu index (built once per call)
# --------------------------------------------------------------------------

class _MenuEntry:
    __slots__ = ('item', 'tokens', 'tokenset', 'joined', 'sizes')

    def __init__(self, item, tokens, sizes):
        self.item = item
        self.tokens = tokens
        self.tokenset = set(tokens)
        self.joined = ' '.join(tokens)
        self.sizes = sizes


class _Context:
    def __init__(self, menu_items):
        self.entries = []
        self.protected_phrases = []  # (plain phrase, protected phrase)

        for item in menu_items:
            raw = item.name.lower().replace('&', ' and ')
            sizes = {int(n) for n in re.findall(r'\d+', ' '.join(re.findall(r'\(([^)]*)\)', raw)))}
            raw = re.sub(r'\([^)]*\)', ' ', raw)           # drop "(6 PCS)"
            has_special = bool(re.search(r'\b\d+\b|\band\b', raw))
            plain_tokens = _tokenize(raw)
            if has_special:
                self._remember_protected(plain_tokens)
            tokens = [_canon(t) for t in _tokenize(_protect(raw)) if t not in SIZE_WORDS]
            if not tokens:
                continue
            self.entries.append(_MenuEntry(item, tokens, sizes))

        self.vocab = {t for e in self.entries for t in e.tokens}
        self.vocab_list = sorted(self.vocab)

    def _remember_protected(self, tokens):
        """Remember short phrases around digits / 'and' so they survive splitting."""
        for i, tok in enumerate(tokens):
            if tok.isdigit():
                lo, hi = max(0, i - 1), min(len(tokens), i + 2)
            elif tok == 'and':
                lo, hi = max(0, i - 1), min(len(tokens), i + 2)
            else:
                continue
            phrase = ' '.join(tokens[lo:hi])
            self.protected_phrases.append((phrase, _protect(phrase)))
        self.protected_phrases.sort(key=lambda p: -len(p[0]))


# --------------------------------------------------------------------------
# Text -> tokens
# --------------------------------------------------------------------------

def _preprocess(text, ctx):
    """Lowercase + fix common phrases. Returns (text, apply_parcel_to_everything)."""
    t = text.lower().replace('&', ' and ').replace('’', "'")
    t = re.sub(r'\bto[\s-]?go\b', ' togo ', t)
    t = re.sub(r'\btake[\s-]?away\b', ' takeaway ', t)
    t = re.sub(r'\bfrench\s+(?:fry|fries|frys|fryes|fri)\b', ' french fries ', t)
    t = re.sub(r'(?<![a-z0-9])[x×*]\s?(\d+)\b', r' #\1 ', t)   # "x2" / "*3": explicit trailing quantity
    t = re.sub(r'\b(\d+)\s?[x×](?![a-z0-9])', r' \1 ', t)       # "2x"
    t = re.sub(r'(\d)([a-z])', r'\1 \2', t)                      # "6pcs" -> "6 pcs"

    for phrase, protected in ctx.protected_phrases:
        t = re.sub(r'\b' + re.escape(phrase) + r'\b', protected, t)

    global_parcel = False
    if _GLOBAL_PARCEL_RE.search(t):
        global_parcel = True
        t = _GLOBAL_PARCEL_RE.sub(' ', t)
    return t, global_parcel


def _fuzzy_fix(tok, ctx):
    if tok in ctx.vocab or tok in _NON_NAME or len(tok) < 4 or tok.isdigit() or tok.startswith(('#', '_')):
        return tok
    match = get_close_matches(tok, ctx.vocab_list, n=1, cutoff=0.78)
    return match[0] if match else tok


def _normalize(tokens, ctx):
    """Aliases -> glue split words ("mo mo") -> snap near-misses to this shop's menu words."""
    out = []
    for tok in tokens:
        if tok.startswith('#') or tok.isdigit() or tok in _NUMBER_WORDS:
            out.append(tok)
        else:
            out.append(_canon(tok))

    merged, i = [], 0
    while i < len(out):
        cur = out[i]
        nxt = out[i + 1] if i + 1 < len(out) else None
        if (nxt and cur.isalpha() and nxt.isalpha() and cur not in _NON_NAME and nxt not in _NON_NAME):
            joined = cur + nxt
            if joined in ctx.vocab:
                merged.append(joined)
                i += 2
                continue
            if not (cur in ctx.vocab and nxt in ctx.vocab):
                close = get_close_matches(joined, ctx.vocab_list, n=1, cutoff=0.85)
                if close:
                    merged.append(close[0])
                    i += 2
                    continue
        merged.append(cur)
        i += 1

    return [_fuzzy_fix(t, ctx) for t in merged]


# --------------------------------------------------------------------------
# Splitting one spoken sentence into per-dish pieces
# --------------------------------------------------------------------------

def _is_size_annotation(toks, i):
    return i + 1 < len(toks) and toks[i + 1] in SIZE_WORDS


def _split_pieces(tokens, ctx):
    toks = list(tokens)
    while toks and toks[0] in LEADING_FILLERS:
        toks.pop(0)
    if not toks:
        return []

    first_is_number = _number_value(toks[0]) is not None or toks[0] in WEAK_NUMBERS
    last_is_number = _number_value(toks[-1]) is not None

    # "veg momo 2 chicken momo 3" - quantity AFTER each dish.
    if not first_is_number and last_is_number and len(toks) >= 2:
        pieces, cur = [], []
        for i, tok in enumerate(toks):
            cur.append(tok)
            if (_number_value(tok) is not None and not _is_size_annotation(toks, i)
                    and any(_is_name_token(x) for x in cur)):
                pieces.append(cur)
                cur = []
        if cur:
            pieces.append(cur)
        return pieces

    # "two chicken momo one veg momo 3 french fries" - quantity BEFORE each dish.
    pieces, cur = [], [toks[0]]
    for i in range(1, len(toks)):
        tok = toks[i]
        has_name = any(_is_name_token(x) for x in cur)

        if (has_name and _number_value(tok) is not None and not tok.startswith('#')
                and not _is_size_annotation(toks, i)
                and any(_is_name_token(x) for x in toks[i + 1:])):
            pieces.append(cur)
            cur = [tok]
            continue

        # "to/for/do" may be the number 2/4 - only believe it if both halves match the menu.
        if has_name and tok in WEAK_NUMBERS and tok not in ('a', 'an') and i + 1 < len(toks):
            right = toks[i:]
            for j in range(1, len(right)):
                if _number_value(right[j]) is not None and not _is_size_annotation(right, j):
                    right = right[:j]
                    break
            left_entry = _parse_piece(cur, ctx)
            right_entry = _parse_piece(right, ctx)
            if (left_entry and right_entry and not left_entry.get('modifier_only') and not right_entry.get('modifier_only')
                    and _confident(left_entry) and _confident(right_entry)):
                pieces.append(cur)
                cur = [tok]
                continue

        cur.append(tok)

    pieces.append(cur)
    return pieces


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def _extract_modifiers(tokens, keep_as_name=frozenset()):
    """
    Splits tokens into (dish name words, is_fried, has_cheese, is_parcel).

    fried / cheese words are normally add-ons ("chicken burger extra cheese"),
    but some dishes are genuinely called that ("Chicken Cheese Momo",
    "Fried Chicken Burger"). Indexes listed in `keep_as_name` stay in the name
    instead of becoming add-ons. Parcel is never part of a dish name.
    """
    is_fried = has_cheese = is_parcel = False
    negate_next = False
    name = []

    for idx, tok in enumerate(tokens):
        if tok in NEGATION_WORDS:
            negate_next = True
            continue
        if tok in PARCEL_WORDS:
            is_parcel = not negate_next
        elif tok in FRIED_WORDS | CHEESE_WORDS:
            if idx in keep_as_name:
                name.append(tok)
            elif tok in FRIED_WORDS:
                is_fried = not negate_next
            else:
                has_cheese = not negate_next
        elif tok in MODIFIER_FILLER:
            continue                      # "extra cheese": drop 'extra', the next word still applies
        elif tok in FILLER_WORDS or tok.isdigit() or tok.startswith('#') or _number_value(tok) is not None:
            pass
        else:
            name.append(tok)
        negate_next = False

    return name, is_fried, has_cheese, is_parcel


def _readings(tokens):
    """
    Every way of deciding which fried/cheese words belong to the dish name and
    which are add-ons. Usually 1-2 modifier words, so this is at most a handful.
    """
    candidates = [i for i, t in enumerate(tokens) if t in FRIED_WORDS | CHEESE_WORDS]
    if len(candidates) > 3:
        candidates = candidates[:3]
    for mask in range(1 << len(candidates)):
        keep = frozenset(c for bit, c in enumerate(candidates) if mask & (1 << bit))
        yield keep, _extract_modifiers(tokens, keep)


def _rank(name_tokens, ctx, want_fried=False, want_cheese=False):
    """Menu entries ranked best-first: [(adjusted_score, raw_score, entry), ...]."""
    if not name_tokens:
        return []
    inp = set(name_tokens)
    joined = ' '.join(name_tokens)
    ranked = []

    for entry in ctx.entries:
        if joined == entry.joined:
            raw = 1.0
        else:
            union = inp | entry.tokenset
            jaccard = len(inp & entry.tokenset) / (len(union) or 1)
            ratio = SequenceMatcher(None, joined, entry.joined).ratio()
            raw = max(jaccard, 0.85 * ratio)

        adjusted = raw
        # Prefer dishes that can actually take the add-on that was asked for.
        if want_fried:
            adjusted += 0.02 if entry.item.supports_fried_option else -0.05
        if want_cheese:
            adjusted += 0.02 if entry.item.supports_cheese_option else -0.05
        ranked.append((adjusted, raw, entry))

    ranked.sort(key=lambda r: r[0], reverse=True)
    return ranked


def _confident(entry):
    return (entry['menu_item'] is not None and not entry.get('review_reason')
            and entry['match_score'] >= MATCH_THRESHOLD)


def _parse_piece(tokens, ctx):
    toks = list(tokens)
    while toks and toks[0] in LEADING_FILLERS:
        toks.pop(0)
    if not toks:
        return None

    raw_text = ' '.join(t.lstrip('#') for t in tokens)

    # ---- quantity -------------------------------------------------------
    quantity, quantity_source = None, None
    if toks[0] in ('a', 'an', 'half') and len(toks) > 1 and toks[1] in ('dozen', 'couple', 'pair', 'few'):
        base = STRONG_NUMBERS[toks[1]]
        quantity = max(1, base // 2) if toks[0] == 'half' else base
        quantity_source = 'leading'
        toks = toks[2:]
    elif toks[0] in ('half-dozen', 'halfdozen'):
        quantity, quantity_source = 6, 'leading'
        toks = toks[1:]
    elif len(toks) > 1 and _number_value(toks[0]) is not None:
        quantity, quantity_source = _number_value(toks[0]), 'leading'
        toks = toks[1:]
    elif len(toks) > 1 and toks[0] in WEAK_NUMBERS:
        quantity, quantity_source = WEAK_NUMBERS[toks[0]], 'leading'
        toks = toks[1:]

    # ---- sizes like "6 pcs" are not quantities --------------------------
    cleaned, i = [], 0
    while i < len(toks):
        if _number_value(toks[i]) is not None and _is_size_annotation(toks, i):
            i += 2
            continue
        cleaned.append(toks[i])
        i += 1

    # ---- trailing quantity: "momo two", "momo x2", "burger 3 parcel" ----
    trailing_token = None
    if quantity is None:
        for idx in range(len(cleaned) - 1, -1, -1):
            tok = cleaned[idx]
            if _number_value(tok) is not None:
                if not any(_is_name_token(x) for x in cleaned[idx + 1:]):
                    quantity = _number_value(tok)
                    trailing_token = tok
                    quantity_source = 'explicit' if tok.startswith('#') else 'trailing'
                    cleaned.pop(idx)
                break
            if _is_name_token(tok):
                break
    if quantity is None:
        quantity = 1

    canon = _normalize(cleaned, ctx)

    # ---- pick the best reading of the fried / cheese / parcel words ------
    parcel = False
    best_reading = None   # (adjusted score, names kept, ranked, flags)
    for keep, (name, fried, cheese, parcel_flag) in _readings(canon):
        parcel = parcel or parcel_flag
        if not name:
            continue
        ranked_r = _rank(name, ctx, want_fried=fried, want_cheese=cheese)
        if not ranked_r:
            continue
        key = (ranked_r[0][0], len(keep))          # tie -> keep more words in the dish name
        if best_reading is None or key > best_reading[0]:
            best_reading = (key, ranked_r, fried, cheese)

    if best_reading is None:
        _, fried, cheese, parcel_flag = _extract_modifiers(canon)
        if fried or cheese or parcel or parcel_flag:
            return {'modifier_only': True, 'raw': raw_text, 'is_fried': fried,
                    'has_extra_cheese': cheese, 'is_parcel': parcel or parcel_flag}
        return None   # nothing but filler words

    _, ranked, is_fried, has_cheese = best_reading

    best_adj, best_raw, best_entry = ranked[0] if ranked else (0.0, 0.0, None)
    second_adj = ranked[1][0] if len(ranked) > 1 else 0.0

    reason = None
    if best_entry is None or best_adj < MATCH_THRESHOLD:
        reason = 'low_match'
    elif best_raw < 0.999 and second_adj >= MATCH_THRESHOLD and (best_adj - second_adj) < AMBIGUITY_MARGIN:
        reason = 'ambiguous'
    elif quantity > MAX_QUANTITY:
        reason = 'quantity'

    # "chicken momo 6" when the dish is "(6 PCS)" -> that 6 is the size, not 6 plates.
    if (best_entry is not None and reason is None and quantity_source == 'trailing'
            and trailing_token is not None and quantity in best_entry.sizes and quantity > 1):
        quantity = 1

    suggestions = [
        {'menu_item_id': e.item.id, 'name': e.item.name, 'score': round(adj, 2)}
        for adj, _raw, e in ranked[:MAX_SUGGESTIONS]
        if adj >= 0.25 and adj >= best_adj - 0.3
    ]

    return {
        'raw': raw_text,
        'quantity': quantity,
        # A hopeless match gets no "best guess" - only suggestions (possibly none).
        'menu_item': best_entry.item if best_entry is not None and reason != 'low_match' else None,
        'match_score': round(best_raw, 2),
        'is_fried': is_fried,
        'has_extra_cheese': has_cheese,
        'is_parcel': parcel,
        'review_reason': reason,
        'ambiguous': reason == 'ambiguous',
        'suggestions': suggestions,
    }


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def parse_order_text(text, menu_items):
    """
    menu_items: iterable of MenuItem instances (already scoped to the right
    shop and is_active=True by the caller).

    Returns a list of dicts, one per detected line:
      {raw, quantity, menu_item (or None), match_score,
       is_fried, has_extra_cheese, is_parcel,
       review_reason (None | 'low_match' | 'ambiguous' | 'quantity'),
       ambiguous, suggestions: [{menu_item_id, name, score}, ...]}

    A line is safe to add automatically only when review_reason is None.
    """
    menu_items = list(menu_items)
    ctx = _Context(menu_items)
    if not ctx.entries:
        return []

    text, global_parcel = _preprocess(text or '', ctx)
    results = []

    for segment in _SPLIT_RE.split(text):
        tokens = _tokenize(segment)
        if not tokens:
            continue
        if ' '.join(tokens) in CANCEL_WORDS:
            continue

        for piece in _split_pieces(tokens, ctx):
            entry = _parse_piece(piece, ctx)
            if entry is None:
                continue

            if entry.get('modifier_only'):
                # "...and parcel" / "...and extra cheese" on its own: applies to what came before.
                if entry['is_parcel']:
                    for earlier in results:
                        earlier['is_parcel'] = True
                if results:
                    if entry['is_fried']:
                        results[-1]['is_fried'] = True
                    if entry['has_extra_cheese']:
                        results[-1]['has_extra_cheese'] = True
                continue

            results.append(entry)

    if global_parcel:
        for entry in results:
            entry['is_parcel'] = True

    return results