"""The content checks: reading numbers and expected words out of a transcript."""

import pytest

from arena.content import digit_stream, has_digits, missing_mentions, normalize_text, number_tokens


@pytest.mark.parametrize(
    "text",
    [
        "Your order number is 47993.",
        "Your order number is 4 7 9 9 3",
        "Order 4-7-9-9-3, let me check",
        "four seven double nine three",
        "four seven nine nine three",
        "forty seven thousand nine hundred ninety three",
        "forty-seven, ninety-nine, three",
        "that is 47,993",
        "चार सात नौ नौ तीन",
        "चार सात डबल नौ तीन",
        "आपका ऑर्डर नंबर ४७९९३ है",
        "सैंतालीस हज़ार नौ सौ तिरानवे",
        "फोर सेवन डबल नाइन थ्री",
        "4 7 double 9 3",
    ],
)
def test_all_the_ways_of_saying_47993(text):
    assert digit_stream(text) == "47993"


def test_wrong_number_is_not_accepted():
    assert not has_digits("Your order number is 4 7 9 3 3", "47993")
    assert not has_digits("चार सात नौ तीन", "47993")
    assert not has_digits("I will check that for you", "47993")


def test_phone_number_spoken_in_groups():
    assert has_digits("नौ आठ सात छह, पाँच चार, तीन दो एक शून्य", "9876543210")
    assert has_digits("98765 43210", "9876543210")
    assert has_digits("triple nine, one two three", "999123")


def test_compound_numbers_stay_whole():
    assert number_tokens("पच्चीस सौ रुपये और पंद्रह सौ") == ["2500", "1500"]
    assert number_tokens("the 23rd of March at 4 30 pm") == ["23", "4", "30"]
    assert number_tokens("two hundred and five") == ["200", "5"]
    assert number_tokens("one lakh twenty thousand") == ["120000"]


def test_hindi_spelling_variants_are_folded():
    assert normalize_text("पाँच") == normalize_text("पांच")
    assert normalize_text("हज़ार") == normalize_text("हजार")


def test_mentions_need_every_group():
    reply = "ठीक है, शनिवार रात 8 बजे की टेबल बुक कर दी है।"
    assert missing_mentions(reply, [["Saturday", "शनिवार"], ["8", "आठ"]]) == []
    assert missing_mentions(reply, [["Sunday", "रविवार"]]) == [["Sunday", "रविवार"]]


def test_number_mentions_match_however_spoken():
    assert missing_mentions("आपको पच्चीस सौ रुपये मिलने थे", [["2500"]]) == []
    assert missing_mentions("you were owed 2,500 rupees", [["2500"]]) == []
    assert missing_mentions("you were owed 3,500 rupees", [["2500"]]) == [["2500"]]
    # A number inside a longer number is not a match.
    assert missing_mentions("flat 125", [["5"]]) == [["5"]]


def test_spelled_out_words_match():
    assert missing_mentions("I have your email as R-A-V-I dot K at gmail dot com", [["ravi"], ["gmail"]]) == []
