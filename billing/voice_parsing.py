"""
Parses spoken/typed order text like "two chicken burgers extra cheese" or
"give me 1 veg momo fried, 2 chicken lolipop please" into structured line
items matched against a shop's actual menu.

Used by OrderViewSet.voice_add — see views.py.
"""
import re
from difflib import SequenceMatcher

WORD_NUMBERS = {
    'a': 1, 'an': 1, 'one': 1, 'single': 1,
    'two': 2, 'to': 2, 'too': 2, 'couple': 2, 'pair': 2,
    'three': 3, 'few': 3,
    'four': 4, 'for': 4,
    'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'dozen': 12,
    'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
    'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'half-dozen': 6, 'halfdozen': 6,
}

# Words that mean "start over / cancel what I just said" — the segment is
# just dropped rather than parsed as an item.
CANCEL_WORDS = {'cancel', 'undo', 'nevermind', 'never mind', 'ignore that'}

FRIED_WORDS = {'fried', 'fry', 'crispy'}
CHEESE_WORDS = {'cheese', 'cheesy', 'chese'}  # "chese" — common speech-to-text mishear
PARCEL_WORDS = {
    'parcel', 'takeaway', 'take-away', 'take', 'packing', 'pack',
    'togo', 'to-go', 'packed', 'packet',
}
NEGATION_WORDS = {'no', 'without', 'not', "don't", 'dont', 'skip'}

# Filler words people naturally say around an order that carry no menu
# information — stripped before matching so they don't hurt the match score.
FILLER_WORDS = {
    'give', 'me', 'please', 'i', 'want', 'need', 'order', 'get', 'add',
    'the', 'a', 'some', 'of', 'plate', 'plates', 'piece', 'pieces',
    'pc', 'pcs', 'item', 'items', 'and', 'with',
}

# How confident a name match needs to be before we auto-add it rather than
# flag it for the person to check by hand.
MATCH_THRESHOLD = 0.55


def _singularize(word):
    """Very small, food-menu-appropriate plural stripper: burgers -> burger,
    fries stays fries (menu items are often already plural), momos -> momo."""
    if len(word) > 3 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 4 and word.endswith('s') and not word.endswith('ss') and not word.endswith('fries'):
        return word[:-1]
    return word


# Leading command/filler words to strip before we even look for a quantity —
# "give me two burgers", "please add one momo", "I want three fries".
LEADING_FILLERS = {
    'give', 'me', 'please', 'i', 'want', 'need', 'order', 'get', 'add',
    'the', 'okay', 'ok', 'um', 'uh', 'can', 'you',
}


def _singularize(word):
    """Very small, food-menu-appropriate plural stripper: burgers -> burger,
    fries stays fries (menu items are often already plural), momos -> momo."""
    if len(word) > 3 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 4 and word.endswith('s') and not word.endswith('ss') and not word.endswith('fries'):
        return word[:-1]
    return word


def _strip_leading_fillers(words):
    while words and words[0].lower().strip('.,') in LEADING_FILLERS:
        words = words[1:]
    return words


def _extract_quantity(text):
    words = _strip_leading_fillers(text.strip().split())
    if not words:
        return 1, ''

    first = words[0].lower().strip('.,')

    # Two-word quantities: "a dozen", "half dozen", "a couple"
    if first in ('a', 'an', 'half') and len(words) > 1:
        second = words[1].lower().strip('.,')
        if second in WORD_NUMBERS:
            base = WORD_NUMBERS[second]
            qty = max(1, base // 2) if first == 'half' else base
            return qty, ' '.join(words[2:])

    if first.isdigit():
        return int(first), ' '.join(words[1:])
    if first in WORD_NUMBERS:
        return WORD_NUMBERS[first], ' '.join(words[1:])

    # Trailing quantity, typed shorthand: "chicken burger x2" / "burger *3"
    last = words[-1].lower().strip('.,')
    match = re.match(r'^[x*]\s?(\d+)$', last)
    if match:
        return int(match.group(1)), ' '.join(words[:-1])
    if last.isdigit() and len(words) > 1:
        return int(last), ' '.join(words[:-1])

    return 1, ' '.join(words)


def _extract_modifiers(text):
    words = text.lower().split()
    is_fried = False
    has_cheese = False
    is_parcel = False
    negate_next = False
    remaining = []

    for word in words:
        clean = word.strip('.,')

        if clean in NEGATION_WORDS:
            negate_next = True
            continue

        if clean in FRIED_WORDS:
            is_fried = not negate_next
            negate_next = False
        elif clean in CHEESE_WORDS:
            has_cheese = not negate_next
            negate_next = False
        elif clean in PARCEL_WORDS:
            is_parcel = not negate_next
            negate_next = False
        elif clean in ('extra', 'more'):
            negate_next = False
            continue  # "extra cheese" — drop the filler, the modifier word right after still applies
        elif clean in FILLER_WORDS:
            negate_next = False
            continue
        else:
            negate_next = False
            remaining.append(_singularize(clean))

    return ' '.join(remaining), is_fried, has_cheese, is_parcel


def _best_menu_match(name_text, menu_items):
    name_text = name_text.lower().strip()
    if not name_text:
        return None, 0.0

    best_item, best_score = None, 0.0
    input_words = set(name_text.split())

    for item in menu_items:
        item_name = item.name.lower()
        item_words = {_singularize(w) for w in item_name.split()}

        if item_name == name_text:
            return item, 1.0

        overlap_score = len(input_words & item_words) / max(len(item_words), 1)
        ratio_score = SequenceMatcher(None, name_text, item_name).ratio()
        score = max(overlap_score, ratio_score)

        if score > best_score:
            best_score = score
            best_item = item

    return best_item, best_score


def parse_order_text(text, menu_items):
    """
    menu_items: iterable of MenuItem instances (already scoped to the
    right shop and is_active=True by the caller).

    Returns a list of dicts, one per detected line:
      {raw, quantity, menu_item (or None), match_score, is_fried, has_extra_cheese, is_parcel}
    """
    segments = re.split(r'[,\n]|(?:\band\b)|(?:\balso\b)', text, flags=re.IGNORECASE)
    results = []

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        if segment.lower() in CANCEL_WORDS:
            continue

        quantity, rest = _extract_quantity(segment)
        name_text, is_fried, has_cheese, is_parcel = _extract_modifiers(rest)
        if not name_text:
            continue
        menu_item, score = _best_menu_match(name_text, menu_items)

        results.append({
            'raw': segment,
            'quantity': quantity,
            'menu_item': menu_item,
            'match_score': round(score, 2),
            'is_fried': is_fried,
            'has_extra_cheese': has_cheese,
            'is_parcel': is_parcel,
        })

    return results