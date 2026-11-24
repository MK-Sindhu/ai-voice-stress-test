"""Checking what the agent said, from a transcript of its audio.

Two questions are asked of a reply:

  digits    did it read back the right number? "4 7 double 9 3", "47993",
            "forty-seven thousand nine hundred ninety-three" and
            "चार सात नौ नौ तीन" must all count as 47993.
  mentions  did it say the expected word, in any of the listed spellings?
            ("Saturday" / "शनिवार" / "सैटरडे")
"""

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\sऀ-ॿ]|_", re.UNICODE)
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_text(text: str) -> str:
    """Lowercase, drop punctuation, and fold spelling variants that speech
    recognisers use interchangeably in Hindi (nukta, chandrabindu, visarga)."""
    text = unicodedata.normalize("NFC", text).lower().translate(_DEVANAGARI_DIGITS)
    text = unicodedata.normalize("NFD", text).replace("़", "")  # nukta: ज़ -> ज
    text = unicodedata.normalize("NFC", text)
    text = text.replace("ँ", "ं")  # chandrabindu -> anusvara: पाँच -> पांच
    text = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", text)  # 47,993 -> 47993
    text = _PUNCT.sub(" ", text).replace("\u0964", " ").replace("\u0965", " ")  # danda
    text = re.sub(r"(?<=\d)(?=[^\W\d])|(?<=[^\W\d])(?=\d)", " ", text)  # 30pm -> 30 pm
    return re.sub(r"\s+", " ", text).strip()


_EN_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

_HI_0_99 = (
    "शून्य एक दो तीन चार पांच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
    "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस "
    "तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस "
    "चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास "
    "पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ "
    "साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर "
    "सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उनासी "
    "अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी "
    "नब्बे इक्यानवे बानवे तिरानवे चौरानवे पंचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(_HI_0_99) == 100

# Other spellings a recogniser may produce, and English digits written in
# Devanagari, which is how Hinglish numbers are often transcribed.
_HI_VARIANTS = {
    "जीरो": 0, "सिफर": 0, "छः": 6, "छे": 6, "छै": 6, "छ": 6, "पंदरह": 15, "पन्द्रह": 15,
    "अठाईस": 28, "अठाइस": 28, "बाइस": 22, "तेइस": 23, "सत्ताइस": 27, "उन्तीस": 29,
    "वन": 1, "टू": 2, "थ्री": 3, "फोर": 4, "फाइव": 5, "सिक्स": 6, "सेवन": 7, "एट": 8,
    "नाइन": 9, "टेन": 10,
}

_UNITS: dict[str, tuple[int, bool]] = {w: (v, True) for w, v in _EN_UNITS.items()}
for _value, _word in enumerate(_HI_0_99):
    _UNITS[normalize_text(_word)] = (_value, False)
for _word, _value in _HI_VARIANTS.items():
    _UNITS[normalize_text(_word)] = (_value, False)

_MULTIPLIERS = {
    "hundred": 100, "thousand": 1000, "lakh": 100000,
    normalize_text("सौ"): 100, normalize_text("हज़ार"): 1000, normalize_text("लाख"): 100000,
}
_REPEATS = {"double": 2, "triple": 3, normalize_text("डबल"): 2, normalize_text("ट्रिपल"): 3}
_ORDINALS = {"st", "nd", "rd", "th"}


def canonical_tokens(text: str) -> list[tuple[str, bool]]:
    """The words of the text in order, with every spoken number turned into
    digits. Each item is (token, is_number).

    Digits spoken one at a time come out one per token; a spoken compound
    ("forty seven", "नौ सौ तिरानवे") comes out as one token.
    """
    out: list[tuple[str, bool]] = []
    total = current = 0
    open_number = False
    last: object = None  # "mult", or the last unit value while a number is open
    repeat = 1

    def flush() -> None:
        nonlocal total, current, open_number, last
        if open_number:
            out.append((str(total + current), True))
        total = current = 0
        open_number, last = False, None

    def emit(digits: str) -> None:
        nonlocal repeat
        out.append((digits * repeat if len(digits) == 1 else digits, True))
        repeat = 1

    tokens = normalize_text(text).split()
    for n, token in enumerate(tokens):
        if token in _ORDINALS and n and tokens[n - 1].isdigit():
            continue  # the "rd" of "23rd"
        if token.isdigit():
            flush()
            emit(token)
        elif token in _REPEATS:
            flush()
            repeat = _REPEATS[token]
        elif token in _MULTIPLIERS:
            mult = _MULTIPLIERS[token]
            if not open_number:
                open_number, current = True, 1
            if mult == 100:
                current *= 100
            else:
                total += current * mult
                current = 0
            last = "mult"
        elif token in _UNITS:
            value, english = _UNITS[token]
            if repeat > 1 and value < 10:
                flush()
                emit(str(value))
            elif open_number and last == "mult":
                current += value
                last = value
            elif open_number and english and isinstance(last, int) and last >= 20 \
                    and last % 10 == 0 and 1 <= value <= 9:
                current += value  # "forty" + "seven"
                last = None
            else:
                flush()
                open_number, current, last = True, value, value
        else:
            flush()
            repeat = 1
            out.append((token, False))
    flush()
    return out


def number_tokens(text: str) -> list[str]:
    """Every number in the text, in order, as digit strings."""
    return [token for token, is_number in canonical_tokens(text) if is_number]


def character_error_rate(reference: str, heard: str) -> float:
    """Share of the reference's characters that were misheard (edit distance
    over length), after normalising both and writing numbers as digits."""
    ref = "".join(t for t, _ in canonical_tokens(reference))
    hyp = "".join(t for t, _ in canonical_tokens(heard))
    return _edit_rate(ref, hyp)


# Rough sound classes, used to compare a Devanagari line with a transcript that
# wrote some of its English words in Latin script ("कैंसल" against "cancel").
_DEV_CONSONANTS = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "च": "c", "छ": "c", "ज": "j", "झ": "j",
    "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n", "त": "t", "थ": "t", "द": "d", "ध": "d",
    "न": "n", "प": "p", "फ": "f", "ब": "b", "भ": "b", "म": "m", "य": "", "र": "r", "ल": "l",
    "व": "v", "श": "s", "ष": "s", "स": "s", "ह": "", "ं": "n", "ङ": "n", "ञ": "n",
}
_LATIN_CONSONANTS = {
    "b": "b", "c": "k", "d": "d", "f": "f", "g": "g", "j": "j", "k": "k", "l": "l", "m": "m",
    "n": "n", "p": "p", "q": "k", "r": "r", "s": "s", "t": "t", "v": "v", "w": "v", "x": "ks",
    "z": "j",
}


def sound_skeleton(text: str) -> str:
    """The consonant sounds of a text, whichever script it is in."""
    out = []
    for token, is_number in canonical_tokens(text):
        if is_number:
            out.append(token)
            continue
        token = token.replace("ch", "c").replace("sh", "s").replace("ph", "f").replace("th", "t")
        for ch in token:
            out.append(_DEV_CONSONANTS.get(ch, _LATIN_CONSONANTS.get(ch, "")))
    return re.sub(r"(.)\1+", r"\1", "".join(out))


def _edit_rate(ref: str, hyp: str) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    row = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, hc in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (rc != hc))
    return row[-1] / len(ref)


def sound_error_rate(reference: str, heard: str) -> float:
    """Like character_error_rate, but on consonant sounds, so it does not
    matter which script the recogniser chose for an English word."""
    return _edit_rate(sound_skeleton(reference), sound_skeleton(heard))


def digit_stream(text: str) -> str:
    """All the numbers in the text run together: "4 7 double 9 3" -> "47993"."""
    return "".join(number_tokens(text))


def has_digits(text: str, expected: str) -> bool:
    return expected in digit_stream(text)


def missing_mentions(text: str, groups: list[list[str]]) -> list[list[str]]:
    """The groups for which none of the alternatives appears in the text.

    Each group is a list of acceptable spellings; every group must be found.
    """
    plain = normalize_text(text)
    squeezed = plain.replace(" ", "")
    numbers = number_tokens(text)
    missing = []
    for group in groups:
        found = False
        for alt in group:
            alt = normalize_text(alt)
            if alt.isdigit():  # a number: match it however it was spoken
                if alt in numbers:
                    found = True
                    break
                continue
            if alt and (alt in plain or alt.replace(" ", "") in squeezed):
                found = True
                break
        if not found:
            missing.append(group)
    return missing
