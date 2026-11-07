"""Per-hunk review maths (3.0, D48).

The property under test is not "the diff looks right" but **"a partial accept leaves the
rest of the revision still pending"** — because that is what turns one binary decision
into a handful of small ones without ever losing the author's remaining work.
"""

import random

import pytest

from app import hunks as H


def _prose(seed: int, n: int = 6, sent: int = 4) -> str:
    r = random.Random(seed)
    subj = ["Kael", "Mira", "the innkeeper", "the boy"]
    verb = ["counted", "weighed", "remembered", "carried"]
    obj = ["the coins", "the ledger", "the ember", "the letter"]
    tail = ["while the bell rang", "as the mist lifted", "though nobody asked"]
    paras = []
    for _ in range(n):
        paras.append(" ".join(
            f"{r.choice(subj)} {r.choice(verb)} {r.choice(obj)} {r.choice(tail)}."
            for _ in range(sent)))
    return "\n\n".join(paras)


# --- the tokenizer is lossless, or every offset is a lie -------------------

@pytest.mark.parametrize("text", [
    "", "one", "one line.\n\ntwo line.\n", "  leading", "trailing   ",
    "quote “exactly.” and — a dash\n\nnext ¶", _prose(1),
])
def test_tokenize_reproduces_the_text_exactly(text: str):
    assert "".join(H.tokenize(text)) == text


# --- cutting a revision into reviewable units -----------------------------

def test_identical_texts_have_nothing_to_review():
    t = _prose(2)
    assert H.hunks(t, t) == []


def test_a_single_change_is_one_hunk_with_readable_sides():
    base = "Hagrid looked at the boy and said nothing for a while."
    firm = base.replace("said nothing", "said not a word")
    hs = H.hunks(base, firm)
    assert len(hs) == 1
    h = hs[0]
    assert h["before"].strip(" ") in base and "nothing" in h["before"]
    assert "not a word" in h["after"]
    # offsets address both texts
    assert base[h["base_start"]:h["base_end"]] == h["before"]
    assert firm[h["prop_start"]:h["prop_end"]] == h["after"]


def test_nearby_fixes_read_as_one_hunk():
    """An author fixes a sentence, not a word — three touches in one paragraph are one
    decision, not three."""
    base = "He counted the coins carefully, then he weighed the ledger, and he said nothing."
    firm = base.replace("carefully", "twice").replace("weighed", "recounted").replace(
        "said nothing", "kept silent")
    assert len(H.hunks(base, firm)) == 1


def test_distant_fixes_stay_separate():
    base = ("One. " + "The sun rose over the harbour and the gulls began to quarrel. " * 4
            + "He counted the coins.")
    firm = base.replace("One.", "Two.").replace("counted the coins", "counted the silver")
    hs = H.hunks(base, firm)
    assert len(hs) == 2, [h["after"] for h in hs]


def test_every_hunk_lands_on_the_text_it_claims():
    base, firm = _prose(3), None
    # a realistic edit: several sentences rewritten
    firm = (base.replace("counted", "counted again").replace("the ledger", "the ledger and the debt")
            .replace("remembered", "could not forget").replace("the ember", "the last ember"))
    for h in H.hunks(base, firm):
        assert base[h["base_start"]:h["base_end"]] == h["before"]
        assert firm[h["prop_start"]:h["prop_end"]] == h["after"]
        assert h["before"].strip() or h["after"].strip()   # never an empty-shell hunk


# --- what a decision set writes -------------------------------------------

def test_accepting_everything_is_the_proposal_byte_for_byte():
    for seed in range(6):
        base, firm = _prose(seed), None
        firm = base.replace("Kael", "Kaelen").replace("while the bell rang", "as the bell tolled")
        assert H.merge(base, firm) == firm
        assert H.merge(base, firm, [h["id"] for h in H.hunks(base, firm)]) == firm


def test_rejecting_everything_is_the_base_byte_for_byte():
    base = _prose(7)
    firm = base.replace("Mira", "Miren").replace("the coins", "the coin")
    assert H.merge(base, firm, []) == base


def test_accepting_one_hunk_writes_that_one_and_no_other():
    base = ("He counted the coins. " + "The gulls quarrelled over the harbour all morning. " * 4
            + "She remembered the ember.")
    firm = base.replace("counted the coins", "counted the silver").replace(
        "remembered the ember", "remembered the last ember")
    hs = H.hunks(base, firm)
    assert len(hs) == 2
    first = hs[0]
    applied = H.merge(base, firm, [first["id"]])
    assert "counted the silver" in applied          # taken
    assert "remembered the last ember" not in applied   # left pending
    assert "She remembered the ember." in applied       # untouched prose survives


def test_a_partial_accept_leaves_the_rest_of_the_revision_pending():
    """The invariant the re-parked proposal depends on: the leftover hunks, applied to what
    was just saved, still produce the Muse's revision exactly."""
    for seed in range(8):
        base = _prose(seed)
        firm = (base.replace("Kael", "Kaelen").replace("the ledger", "the ledger and the debt")
                .replace("the boy", "the youngest boy").replace("Mira", "Miren"))
        hs = H.hunks(base, firm)
        if len(hs) < 2:
            continue
        taken = {h["id"] for h in hs[: len(hs) // 2]}
        applied = H.merge(base, firm, taken)
        # 1. what is left can finish the job, exactly
        assert H.merge(applied, firm) == firm
        remaining = H.hunks(applied, firm)
        assert remaining, "a partial accept must leave something pending"
        # 2. accepting some hunks can only shrink the remaining work (adjacent leftovers
        #    may merge, but no new change is ever invented)
        assert len(remaining) <= len(hs) - len(taken), (len(remaining), len(hs), len(taken))
        # 3. and no accepted hunk's intent was lost
        for h in hs:
            if h["id"] in taken:
                assert h["after"].strip() in applied


def test_unknown_hunk_ids_are_refused_rather_than_guessed():
    base = "He counted the coins."
    firm = "He counted the silver."
    with pytest.raises(ValueError):
        H.merge(base, firm, [99])


def test_a_wholesale_rewrite_is_one_hunk_not_a_thousand():
    base = "The harbour was quiet in the grey hour before dawn."
    firm = ("Gulls quarrelled over the water while the lamps guttered, and nobody at the "
            "quay noticed the boy counting coins he could not spend.")
    hs = H.hunks(base, firm)
    assert len(hs) == 1
    assert H.merge(base, firm, [hs[0]["id"]]) == firm
