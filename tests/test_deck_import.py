import deck_import


def test_parse_decklist_aggregates_duplicate_lines_and_skips_sections():
    deck_text = """
Deck
4 Lightning Bolt
2 Lightning Bolt
Commander
1 Atraxa, Praetors' Voice
"""

    entries, unmatched = deck_import.parse_decklist(deck_text)

    assert unmatched == []
    assert entries == [
        deck_import.DeckEntry(count=6, name="Lightning Bolt"),
        deck_import.DeckEntry(count=1, name="Atraxa, Praetors' Voice"),
    ]


def test_parse_decklist_supports_set_code_and_collector_number():
    entries, unmatched = deck_import.parse_decklist("1 Opt (eld) 59\n")

    assert unmatched == []
    assert entries == [
        deck_import.DeckEntry(
            count=1,
            name="Opt",
            set_code="eld",
            collector_number="59",
        )
    ]


def test_parse_decklist_collects_unmatched_lines():
    entries, unmatched = deck_import.parse_decklist("hello world\n2 Fire // Ice\n")

    assert entries == [deck_import.DeckEntry(count=2, name="Fire // Ice")]
    assert unmatched == ["hello world"]


def test_import_decklist_downloads_images_and_applies_counts(tmp_path):
    def fake_fetch_json(url):
        if "named" in url:
            return {
                "name": "Lightning Bolt",
                "set": "clu",
                "collector_number": "141",
                "image_uris": {"png": "https://img/lightning-bolt.png"},
            }
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_fetch_bytes(url):
        assert url == "https://img/lightning-bolt.png"
        return b"png-bytes"

    result = deck_import.import_decklist(
        "4 Lightning Bolt\n",
        str(tmp_path),
        fetch_json=fake_fetch_json,
        fetch_bytes=fake_fetch_bytes,
    )

    assert result.unmatched_lines == []
    assert result.failed_cards == []
    assert [card.filename for card in result.imported] == [
        "scryfall_clu_141_lightning-bolt.png"
    ]
    assert (tmp_path / "scryfall_clu_141_lightning-bolt.png").read_bytes() == b"png-bytes"

    print_dict = {"cards": {}}
    deck_import.apply_imported_counts(print_dict, result.imported)
    assert print_dict["cards"] == {"scryfall_clu_141_lightning-bolt.png": 4}


def test_import_decklist_reports_partial_failures(tmp_path):
    def fake_fetch_json(url):
        if "named" in url and "Lightning+Bolt" in url:
            return {
                "name": "Lightning Bolt",
                "set": "clu",
                "collector_number": "141",
                "image_uris": {"png": "https://img/lightning-bolt.png"},
            }
        raise ValueError("not found")

    result = deck_import.import_decklist(
        "4 Lightning Bolt\n2 Missing Card\n",
        str(tmp_path),
        fetch_json=fake_fetch_json,
        fetch_bytes=lambda _url: b"image",
    )

    assert [card.filename for card in result.imported] == [
        "scryfall_clu_141_lightning-bolt.png"
    ]
    assert result.failed_cards == ["Missing Card"]
