import base64
import json
import logging
import os

import high_res


VALID_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
)
VALID_PNG_BYTES = base64.b64decode(VALID_PNG_BASE64)


def test_build_card_context_prefers_import_metadata():
    print_dict = {
        "card_metadata": {
            "scryfall_eld_59_opt.png": {
                "name": "Opt",
                "set_code": "eld",
                "collector_number": "59",
            }
        }
    }

    context = high_res.build_card_context("scryfall_eld_59_opt.png", print_dict)

    assert context.query == "Opt"
    assert context.display_name == "Opt"
    assert context.set_code == "eld"
    assert context.collector_number == "59"


def test_build_card_context_falls_back_to_scryfall_filename_parts():
    context = high_res.build_card_context(
        "scryfall_mom_137_etali-primal-conqueror.png",
        {},
    )

    assert context.query == "Etali Primal Conqueror"
    assert context.display_name == "Etali Primal Conqueror"
    assert context.set_code == "mom"
    assert context.collector_number == "137"


def test_build_card_context_uses_normalized_override_name_when_metadata_missing():
    print_dict = {
        "high_res_front_overrides": {
            "scryfall_lci_88_aclazotz-deepest-betrayal.png": {
                "name": "Aclazotz, Deepest Betrayal (Normal) [LCI] {88} (1)"
            }
        }
    }

    context = high_res.build_card_context(
        "scryfall_lci_88_aclazotz-deepest-betrayal.png",
        print_dict,
    )

    assert context.query == "Aclazotz, Deepest Betrayal"
    assert context.set_code == "lci"
    assert context.collector_number == "88"


def test_build_card_context_uses_front_face_when_metadata_name_is_double_faced():
    print_dict = {
        "card_metadata": {
            "scryfall_dka_81_afflicted-deserter.png": {
                "name": "Afflicted Deserter // Werewolf Ransacker",
                "set_code": "dka",
                "collector_number": "81",
            }
        }
    }

    context = high_res.build_card_context(
        "scryfall_dka_81_afflicted-deserter.png",
        print_dict,
    )

    assert context.query == "Afflicted Deserter"
    assert context.set_code == "dka"
    assert context.collector_number == "81"


def test_build_search_payload_uses_dpi_filters_and_sources():
    payload = high_res.build_search_payload(
        "Opt",
        300,
        1200,
        page_size=60,
        page_start=120,
    )

    assert payload["query"] == "Opt"
    assert payload["cardTypes"] == []
    assert payload["pageSize"] == 60
    assert payload["pageStart"] == 120
    assert payload["searchSettings"]["filterSettings"]["minimumDPI"] == 300
    assert payload["searchSettings"]["filterSettings"]["maximumDPI"] == 1200
    assert payload["sortBy"] == "dateCreatedDescending"
    assert payload["searchSettings"]["searchTypeSettings"]["fuzzySearch"] is True
    assert payload["searchSettings"]["sourceSettings"]["sources"][:3] == [
        [1, True],
        [2, True],
        [3, True],
    ]


def test_search_high_res_candidates_queries_backend():
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append((url, body))
        return {
            "cards": [
                {
                    "identifier": "abc123",
                    "name": "Opt",
                    "dpi": 1200,
                    "extension": "png",
                    "downloadLink": "https://download/opt.png",
                    "smallThumbnailUrl": "https://thumb/small",
                    "mediumThumbnailUrl": "https://thumb/medium",
                    "sourceId": 7,
                    "sourceName": "Test Source",
                }
            ]
        }

    context = high_res.CardContext(
        filename="scryfall_eld_59_opt.png",
        query="Opt",
        display_name="Opt",
    )
    results = high_res.search_high_res_candidates(
        context,
        "https://example.com/",
        300,
        1200,
        page_start=60,
        page_size=60,
        fetch_json=fake_fetch_json,
    )

    assert len(results) == 1
    assert results[0].identifier == "abc123"
    assert results[0].download_link == "https://download/opt.png"
    assert results[0].source_id == 7
    assert calls[0][0] == "https://example.com/2/exploreSearch/"
    assert calls[0][1]["searchSettings"]["filterSettings"]["minimumDPI"] == 300
    assert calls[0][1]["pageStart"] == 60
    assert calls[0][1]["pageSize"] == 60


def test_search_high_res_page_returns_total_count():
    result = high_res.search_high_res_page(
        high_res.CardContext(filename="x.png", query="Opt", display_name="Opt"),
        "https://example.com/",
        300,
        1200,
        page_start=120,
        page_size=60,
        fetch_json=lambda url, body=None, headers=None: {
            "cards": [
                {
                    "identifier": "abc123",
                    "name": "Opt",
                    "dpi": 1200,
                    "extension": "png",
                    "downloadLink": "https://download/opt.png",
                    "smallThumbnailUrl": "https://thumb/small",
                    "mediumThumbnailUrl": "https://thumb/medium",
                    "sourceId": 7,
                    "sourceName": "Test Source",
                }
            ],
            "count": 1274,
        },
    )

    assert result.total_count == 1274
    assert result.page_start == 120
    assert result.page_size == 60
    assert len(result.candidates) == 1


def test_search_new_art_page_returns_scryfall_print_candidates():
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append(url)
        if url == "https://api.scryfall.com/cards/eld/59":
            return {
                "id": "current-print",
                "prints_search_uri": "https://api.scryfall.com/cards/search?order=released&q=oracleid%3Aabc&unique=prints",
            }
        return {
            "object": "list",
            "has_more": False,
            "total_cards": 2,
            "data": [
                {
                    "id": "print-1",
                    "name": "Opt",
                    "set": "eld",
                    "set_name": "Throne of Eldraine",
                    "collector_number": "59",
                    "image_uris": {
                        "small": "https://cards.scryfall.io/small/front/a/b/card1.jpg",
                        "normal": "https://cards.scryfall.io/normal/front/a/b/card1.jpg",
                        "large": "https://cards.scryfall.io/large/front/a/b/card1.jpg",
                        "png": "https://cards.scryfall.io/png/front/a/b/card1.png",
                    },
                },
                {
                    "id": "print-2",
                    "name": "Opt",
                    "set": "sta",
                    "set_name": "Strixhaven Mystical Archive",
                    "collector_number": "19",
                    "image_uris": {
                        "small": "https://cards.scryfall.io/small/front/c/d/card2.jpg",
                        "normal": "https://cards.scryfall.io/normal/front/c/d/card2.jpg",
                        "large": "https://cards.scryfall.io/large/front/c/d/card2.jpg",
                        "png": "https://cards.scryfall.io/png/front/c/d/card2.png",
                    },
                },
            ],
        }

    context = high_res.CardContext(
        filename="scryfall_eld_59_opt.png",
        query="Opt",
        display_name="Opt",
        set_code="eld",
        collector_number="59",
    )
    result = high_res.search_new_art_page(
        context,
        high_res.NEW_ART_SOURCE_SCRYFALL,
        fetch_json=fake_fetch_json,
    )

    assert result.total_count == 2
    assert [candidate.identifier for candidate in result.candidates] == ["print-1", "print-2"]
    assert result.candidates[0].art_source == high_res.NEW_ART_SOURCE_SCRYFALL
    assert result.candidates[0].download_link.endswith("card1.png")
    assert result.candidates[0].set_name == "Throne of Eldraine"
    assert result.candidates[1].set_code == "sta"
    assert calls[0] == "https://api.scryfall.com/cards/eld/59"


def test_search_new_art_page_filters_scryfall_by_set_code():
    def fake_fetch_json(url, body=None, headers=None):
        if url == "https://api.scryfall.com/cards/eld/59":
            return {
                "id": "current-print",
                "prints_search_uri": "https://api.scryfall.com/cards/search?order=released&q=oracleid%3Aabc&unique=prints",
            }
        return {
            "object": "list",
            "has_more": False,
            "total_cards": 2,
            "data": [
                {
                    "id": "print-1",
                    "name": "Opt",
                    "set": "eld",
                    "set_name": "Throne of Eldraine",
                    "collector_number": "59",
                    "image_uris": {"png": "https://cards.scryfall.io/png/front/a/b/card1.png"},
                },
                {
                    "id": "print-2",
                    "name": "Opt",
                    "set": "sta",
                    "set_name": "Strixhaven Mystical Archive",
                    "collector_number": "19",
                    "image_uris": {"png": "https://cards.scryfall.io/png/front/c/d/card2.png"},
                },
            ],
        }

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt", set_code="eld", collector_number="59")
    result = high_res.search_new_art_page(
        context,
        high_res.NEW_ART_SOURCE_SCRYFALL,
        set_filter="sta",
        fetch_json=fake_fetch_json,
    )

    assert result.total_count == 1
    assert [candidate.identifier for candidate in result.candidates] == ["print-2"]


def test_search_new_art_page_filters_scryfall_by_set_name():
    def fake_fetch_json(url, body=None, headers=None):
        if url == "https://api.scryfall.com/cards/eld/59":
            return {
                "id": "current-print",
                "prints_search_uri": "https://api.scryfall.com/cards/search?order=released&q=oracleid%3Aabc&unique=prints",
            }
        return {
            "object": "list",
            "has_more": False,
            "total_cards": 2,
            "data": [
                {
                    "id": "print-1",
                    "name": "Opt",
                    "set": "eld",
                    "set_name": "Throne of Eldraine",
                    "collector_number": "59",
                    "image_uris": {"png": "https://cards.scryfall.io/png/front/a/b/card1.png"},
                },
                {
                    "id": "print-2",
                    "name": "Opt",
                    "set": "sta",
                    "set_name": "Strixhaven Mystical Archive",
                    "collector_number": "19",
                    "image_uris": {"png": "https://cards.scryfall.io/png/front/c/d/card2.png"},
                },
            ],
        }

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt", set_code="eld", collector_number="59")
    result = high_res.search_new_art_page(
        context,
        high_res.NEW_ART_SOURCE_SCRYFALL,
        set_filter="mystical",
        fetch_json=fake_fetch_json,
    )

    assert result.total_count == 1
    assert [candidate.identifier for candidate in result.candidates] == ["print-2"]


def test_search_new_art_page_filtered_scryfall_pagination_fetches_additional_raw_pages():
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append(url)
        if url == "https://api.scryfall.com/cards/eld/59":
            return {
                "id": "current-print",
                "prints_search_uri": "https://api.scryfall.com/cards/search?order=released&q=oracleid%3Aabc&unique=prints",
            }
        if "next=2" in url:
            return {
                "object": "list",
                "has_more": False,
                "total_cards": 4,
                "data": [
                    {
                        "id": "print-3",
                        "name": "Opt",
                        "set": "sta",
                        "set_name": "Strixhaven Mystical Archive",
                        "collector_number": "21",
                        "image_uris": {"png": "https://cards.scryfall.io/png/front/e/f/card3.png"},
                    },
                    {
                        "id": "print-4",
                        "name": "Opt",
                        "set": "sta",
                        "set_name": "Strixhaven Mystical Archive",
                        "collector_number": "22",
                        "image_uris": {"png": "https://cards.scryfall.io/png/front/g/h/card4.png"},
                    },
                ],
            }
        return {
            "object": "list",
            "has_more": True,
            "next_page": "https://api.scryfall.com/cards/search?next=2",
            "total_cards": 4,
            "data": [
                {
                    "id": "print-1",
                    "name": "Opt",
                    "set": "eld",
                    "set_name": "Throne of Eldraine",
                    "collector_number": "59",
                    "image_uris": {"png": "https://cards.scryfall.io/png/front/a/b/card1.png"},
                },
                {
                    "id": "print-2",
                    "name": "Opt",
                    "set": "eld",
                    "set_name": "Throne of Eldraine",
                    "collector_number": "60",
                    "image_uris": {"png": "https://cards.scryfall.io/png/front/c/d/card2.png"},
                },
            ],
        }

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt", set_code="eld", collector_number="59")
    result = high_res.search_new_art_page(
        context,
        high_res.NEW_ART_SOURCE_SCRYFALL,
        page_start=1,
        page_size=1,
        set_filter="mystical",
        fetch_json=fake_fetch_json,
    )

    assert [candidate.identifier for candidate in result.candidates] == ["print-4"]
    assert any("next=2" in url for url in calls)


def test_search_new_art_page_name_mode_uses_manual_mpcfill_search_text():
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append((url, body))
        return {"cards": []}

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")
    high_res.search_new_art_page(
        context,
        high_res.NEW_ART_SOURCE_MPCFILL,
        backend_url="https://example.com/",
        min_dpi=300,
        max_dpi=1200,
        search_text="Island",
        search_mode="name",
        fetch_json=fake_fetch_json,
    )

    assert calls[0][1]["query"] == "Island"


def test_search_new_art_page_name_mode_falls_back_to_context_name_for_blank_text():
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append((url, body))
        return {"cards": []}

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")
    high_res.search_new_art_page(
        context,
        high_res.NEW_ART_SOURCE_MPCFILL,
        backend_url="https://example.com/",
        min_dpi=300,
        max_dpi=1200,
        search_text="   ",
        search_mode="name",
        fetch_json=fake_fetch_json,
    )

    assert calls[0][1]["query"] == "Opt"


def test_search_new_art_page_artist_mode_uses_manual_search_text():
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append((url, body))
        return {"cards": []}

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")
    high_res.search_new_art_page(
        context,
        high_res.NEW_ART_SOURCE_MPCFILL,
        backend_url="https://example.com/",
        min_dpi=300,
        max_dpi=1200,
        search_text="John Avon",
        search_mode="artist",
        fetch_json=fake_fetch_json,
    )

    assert calls[0][1]["query"] == "John Avon"


def test_search_new_art_page_artist_mode_requires_search_text():
    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")

    try:
        high_res.search_new_art_page(
            context,
            high_res.NEW_ART_SOURCE_MPCFILL,
            backend_url="https://example.com/",
            min_dpi=300,
            max_dpi=1200,
            search_text="",
            search_mode="artist",
            fetch_json=lambda url, body=None, headers=None: {"cards": []},
        )
    except ValueError as exc:
        assert "artist name" in str(exc)
    else:
        raise AssertionError("Expected artist-mode search to require input")


def test_search_high_res_page_uses_in_memory_cache(monkeypatch):
    high_res.clear_all_high_res_caches()
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append((url, body))
        return {
            "cards": [
                {
                    "identifier": "abc123",
                    "name": "Opt",
                    "dpi": 1200,
                    "extension": "png",
                    "downloadLink": "https://download/opt.png",
                    "smallThumbnailUrl": "https://thumb/small",
                    "mediumThumbnailUrl": "https://thumb/medium",
                    "sourceId": 7,
                    "sourceName": "Test Source",
                }
            ],
            "count": 1274,
        }

    monkeypatch.setattr(high_res, "_fetch_json", fake_fetch_json)

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")
    first = high_res.search_high_res_page(
        context,
        "https://example.com/",
        300,
        1200,
        page_start=0,
        page_size=60,
    )
    second = high_res.search_high_res_page(
        context,
        "https://example.com/",
        300,
        1200,
        page_start=0,
        page_size=60,
    )

    assert first == second
    assert len(calls) == 1
    high_res.clear_all_high_res_caches()


def test_search_high_res_page_cache_expires(monkeypatch):
    high_res.clear_all_high_res_caches()
    fetch_calls = []
    current_time = {"value": 100.0}

    def fake_fetch_json(url, body=None, headers=None):
        fetch_calls.append((url, body))
        return {
            "cards": [
                {
                    "identifier": f"abc{len(fetch_calls)}",
                    "name": "Opt",
                    "dpi": 1200,
                    "extension": "png",
                    "downloadLink": "https://download/opt.png",
                    "smallThumbnailUrl": "https://thumb/small",
                    "mediumThumbnailUrl": "https://thumb/medium",
                    "sourceId": 7,
                    "sourceName": "Test Source",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr(high_res, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(high_res.time, "time", lambda: current_time["value"])

    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")
    first = high_res.search_high_res_page(context, "https://example.com/", 300, 1200)
    current_time["value"] += high_res.CFG.HighResCacheTTLSeconds + 1
    second = high_res.search_high_res_page(context, "https://example.com/", 300, 1200)

    assert first.candidates[0].identifier == "abc1"
    assert second.candidates[0].identifier == "abc2"
    assert len(fetch_calls) == 2
    high_res.clear_all_high_res_caches()


def test_search_high_res_page_cache_respects_memory_limit_with_disk_fallback(monkeypatch):
    high_res.clear_all_high_res_caches()
    monkeypatch.setattr(high_res.CFG, "HighResSearchCacheMemoryMB", 0)
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append((url, body))
        return {
            "cards": [
                {
                    "identifier": "abc123",
                    "name": "Opt",
                    "dpi": 1200,
                    "extension": "png",
                    "downloadLink": "https://download/opt.png",
                    "smallThumbnailUrl": "https://thumb/small",
                    "mediumThumbnailUrl": "https://thumb/medium",
                    "sourceId": 7,
                    "sourceName": "Test Source",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr(high_res, "_fetch_json", fake_fetch_json)
    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")
    high_res.search_high_res_page(context, "https://example.com/", 300, 1200)
    high_res._SEARCH_PAGE_CACHE.clear()
    high_res.search_high_res_page(context, "https://example.com/", 300, 1200)

    assert len(calls) == 1
    high_res.clear_all_high_res_caches()


def test_search_high_res_page_uses_disk_cache_across_memory_reset(monkeypatch, tmp_path):
    high_res.clear_all_high_res_caches()
    monkeypatch.setattr(high_res, "cwd", str(tmp_path))
    calls = []

    def fake_fetch_json(url, body=None, headers=None):
        calls.append((url, body))
        return {
            "cards": [
                {
                    "identifier": "abc123",
                    "name": "Opt",
                    "dpi": 1200,
                    "extension": "png",
                    "downloadLink": "https://download/opt.png",
                    "smallThumbnailUrl": "https://thumb/small",
                    "mediumThumbnailUrl": "https://thumb/medium",
                    "sourceId": 7,
                    "sourceName": "Test Source",
                }
            ],
            "count": 1274,
        }

    monkeypatch.setattr(high_res, "_fetch_json", fake_fetch_json)
    context = high_res.CardContext(filename="x.png", query="Opt", display_name="Opt")

    first = high_res.search_high_res_page(
        context,
        "https://example.com/",
        300,
        1200,
        page_start=0,
        page_size=60,
    )
    high_res._SEARCH_PAGE_CACHE.clear()
    second = high_res.search_high_res_page(
        context,
        "https://example.com/",
        300,
        1200,
        page_start=0,
        page_size=60,
    )

    assert first == second
    assert len(calls) == 1
    assert os.path.exists(high_res._high_res_cache_dir("search"))
    high_res.clear_all_high_res_caches()


def test_fetch_preview_bytes_uses_shared_image_cache(monkeypatch):
    high_res.clear_all_high_res_caches()
    monkeypatch.setattr(high_res.CFG, "HighResImageCacheMemoryMB", 64)
    calls = []

    def fake_fetch_bytes(url):
        calls.append(url)
        return b"thumb-bytes"

    monkeypatch.setattr(high_res, "_fetch_bytes", fake_fetch_bytes)

    first = high_res.fetch_preview_bytes("https://thumb/small", cache_kind="thumbnail")
    second = high_res.fetch_preview_bytes("https://thumb/small", cache_kind="thumbnail")

    assert first == b"thumb-bytes"
    assert second == b"thumb-bytes"
    assert len(calls) == 1
    high_res.clear_all_high_res_caches()


def test_fetch_preview_bytes_uses_disk_cache_across_memory_reset(monkeypatch, tmp_path):
    high_res.clear_all_high_res_caches()
    monkeypatch.setattr(high_res, "cwd", str(tmp_path))
    calls = []

    def fake_fetch_bytes(url):
        calls.append(url)
        return b"thumb-bytes"

    monkeypatch.setattr(high_res, "_fetch_bytes", fake_fetch_bytes)

    first = high_res.fetch_preview_bytes("https://thumb/small", cache_kind="thumbnail")
    high_res._IMAGE_CACHE.clear()
    second = high_res.fetch_preview_bytes("https://thumb/small", cache_kind="thumbnail")

    assert first == b"thumb-bytes"
    assert second == b"thumb-bytes"
    assert len(calls) == 1
    assert os.path.exists(high_res._high_res_cache_dir("image"))
    high_res.clear_all_high_res_caches()


def test_get_double_faced_back_context_uses_cache(monkeypatch):
    high_res.clear_all_high_res_caches()
    calls = []
    print_dict = {
        "backsides": {"scryfall_mid_1_delver-of-secrets.png": "__scryfall_mid_1_insectile-aberration.png"}
    }
    front_context = high_res.CardContext(
        filename="scryfall_mid_1_delver-of-secrets.png",
        query="Delver of Secrets",
        display_name="Delver of Secrets",
        set_code="mid",
        collector_number="1",
    )

    def fake_fetch_json(url, body=None, headers=None):
        calls.append(url)
        return {
            "card_faces": [{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}]
        }

    monkeypatch.setattr(high_res, "_fetch_json", fake_fetch_json)

    first = high_res.get_double_faced_back_context(
        print_dict,
        "scryfall_mid_1_delver-of-secrets.png",
        front_context,
    )
    second = high_res.get_double_faced_back_context(
        print_dict,
        "scryfall_mid_1_delver-of-secrets.png",
        front_context,
    )

    assert first == second
    assert len(calls) == 1
    high_res.clear_all_high_res_caches()


def test_apply_high_res_candidate_writes_bytes_and_tracks_override(tmp_path):
    candidate = high_res.HighResCandidate(
        identifier="drive123",
        name="Opt",
        dpi=1200,
        extension="png",
        download_link="https://download/opt.png",
        small_thumbnail_url="https://thumb/small",
        medium_thumbnail_url="https://thumb/medium",
        source_id=7,
        source_name="Test Source",
    )
    expected = VALID_PNG_BYTES
    print_dict = {"high_res_front_overrides": {}}

    high_res.apply_high_res_candidate(
        print_dict,
        str(tmp_path),
        "scryfall_eld_59_opt.png",
        candidate,
        fetch_bytes=lambda _url: expected,
    )

    assert (tmp_path / "scryfall_eld_59_opt.png").read_bytes() == expected
    assert print_dict["high_res_front_overrides"] == {
        "scryfall_eld_59_opt.png": {
            "art_source": "mpcfill",
            "identifier": "drive123",
            "name": "Opt",
            "dpi": 1200,
            "extension": "png",
            "download_link": "https://download/opt.png",
            "source_id": 7,
            "source_name": "Test Source",
            "small_thumbnail_url": "https://thumb/small",
            "medium_thumbnail_url": "https://thumb/medium",
        }
    }


def test_apply_high_res_candidate_crops_mpcfill_art_before_writing(monkeypatch, tmp_path):
    candidate = high_res.HighResCandidate(
        identifier="drive123",
        name="Opt",
        dpi=1200,
        extension="png",
        download_link="https://download/opt.png",
        small_thumbnail_url="https://thumb/small",
        medium_thumbnail_url="https://thumb/medium",
        source_id=7,
        source_name="Test Source",
    )
    monkeypatch.setattr(high_res.image, "image_from_bytes", lambda _data: "decoded-image")
    monkeypatch.setattr(high_res.image, "crop_image", lambda *_args, **_kwargs: "cropped-image")
    monkeypatch.setattr(high_res.image, "image_to_bytes", lambda image_value: b"cropped-bytes" if image_value == "cropped-image" else b"other")

    print_dict = {"high_res_front_overrides": {}}
    high_res.apply_high_res_candidate(
        print_dict,
        str(tmp_path),
        "scryfall_eld_59_opt.png",
        candidate,
        fetch_bytes=lambda _url: VALID_PNG_BYTES,
    )

    assert (tmp_path / "scryfall_eld_59_opt.png").read_bytes() == b"cropped-bytes"
    assert print_dict["high_res_front_overrides"]["scryfall_eld_59_opt.png"]["art_source"] == "mpcfill"


def test_download_high_res_image_falls_back_to_drive_identifier():
    expected = VALID_PNG_BYTES

    result = high_res.download_high_res_image(
        "drive123",
        "https://download/opt.png",
        fetch_bytes=lambda _url: (_ for _ in ()).throw(OSError("boom")),
        fetch_text=lambda _url: base64.b64encode(expected).decode("ascii"),
    )

    assert result == expected


def test_download_high_res_image_logs_direct_download_failure(caplog):
    with caplog.at_level(logging.WARNING):
        result = high_res.download_high_res_image(
            "drive123",
            "https://download/opt.png",
            fetch_bytes=lambda _url: (_ for _ in ()).throw(OSError("boom")),
            fetch_text=lambda _url: VALID_PNG_BASE64,
        )

    assert result == VALID_PNG_BYTES
    assert "operation=direct_download" in caplog.text


def test_download_high_res_image_falls_back_when_direct_payload_is_not_an_image():
    result = high_res.download_high_res_image(
        "drive123",
        "https://download/opt.png",
        fetch_bytes=lambda _url: b"<html>not an image</html>",
        fetch_text=lambda _url: VALID_PNG_BASE64,
    )

    assert result == VALID_PNG_BYTES


def test_download_high_res_image_raises_when_all_sources_are_invalid():
    try:
        high_res.download_high_res_image(
            "drive123",
            "https://download/opt.png",
            fetch_bytes=lambda _url: b"",
            fetch_text=lambda _url: "not-base64-image-data",
        )
    except ValueError as exc:
        assert "could not be downloaded as a valid image file" in str(exc)
    else:
        raise AssertionError("Expected download_high_res_image to fail")


def test_get_double_faced_back_context_uses_scryfall_faces():
    print_dict = {
        "backsides": {"scryfall_mid_1_delver-of-secrets.png": "__scryfall_mid_1_insectile-aberration.png"}
    }
    front_context = high_res.CardContext(
        filename="scryfall_mid_1_delver-of-secrets.png",
        query="Delver of Secrets",
        display_name="Delver of Secrets",
        set_code="mid",
        collector_number="1",
    )

    back_context = high_res.get_double_faced_back_context(
        print_dict,
        "scryfall_mid_1_delver-of-secrets.png",
        front_context,
        fetch_json=lambda url, body=None, headers=None: {
            "card_faces": [{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}]
        },
    )

    assert back_context is not None
    assert back_context.filename == "__scryfall_mid_1_insectile-aberration.png"
    assert back_context.query == "Insectile Aberration"


def test_maybe_find_matching_backside_uses_scryfall_candidate_back_link():
    print_dict = {
        "backsides": {"scryfall_mid_1_delver-of-secrets.png": "__scryfall_mid_1_insectile-aberration.png"}
    }
    front_context = high_res.CardContext(
        filename="scryfall_mid_1_delver-of-secrets.png",
        query="Delver of Secrets",
        display_name="Delver of Secrets",
        set_code="mid",
        collector_number="1",
    )
    front_candidate = high_res.HighResCandidate(
        identifier="front123",
        name="Delver of Secrets",
        dpi=0,
        extension="png",
        download_link="https://cards.scryfall.io/png/front.png",
        small_thumbnail_url="https://cards.scryfall.io/small/front.jpg",
        medium_thumbnail_url="https://cards.scryfall.io/large/front.jpg",
        source_id=0,
        source_name="Scryfall",
        art_source=high_res.NEW_ART_SOURCE_SCRYFALL,
        set_code="mid",
        collector_number="1",
        back_identifier="front123:back",
        back_download_link="https://cards.scryfall.io/png/back.png",
        back_small_thumbnail_url="https://cards.scryfall.io/small/back.jpg",
        back_medium_thumbnail_url="https://cards.scryfall.io/large/back.jpg",
    )

    result = high_res.maybe_find_matching_backside(
        print_dict,
        "scryfall_mid_1_delver-of-secrets.png",
        front_context,
        front_candidate,
        "",
    )

    assert result is not None
    assert result.filename == "__scryfall_mid_1_insectile-aberration.png"
    assert result.candidate.download_link == "https://cards.scryfall.io/png/back.png"
    assert result.candidate.art_source == high_res.NEW_ART_SOURCE_SCRYFALL


def test_find_matching_backside_candidate_prefers_same_source_and_name():
    front_candidate = high_res.HighResCandidate(
        identifier="front123",
        name="Delver of Secrets",
        dpi=800,
        extension="png",
        download_link="https://download/front.png",
        small_thumbnail_url="https://thumb/front-small",
        medium_thumbnail_url="https://thumb/front-medium",
        source_id=3,
        source_name="Chilli_Axe",
    )
    back_context = high_res.CardContext(
        filename="__scryfall_mid_1_insectile-aberration.png",
        query="Insectile Aberration",
        display_name="Insectile Aberration",
    )
    seen_payloads = []

    def fake_fetch_json(url, body=None, headers=None):
        seen_payloads.append(body)
        return {
            "cards": [
                {
                    "identifier": "back123",
                    "name": "Insectile Aberration",
                    "dpi": 800,
                    "extension": "png",
                    "downloadLink": "https://download/back.png",
                    "smallThumbnailUrl": "https://thumb/back-small",
                    "mediumThumbnailUrl": "https://thumb/back-medium",
                    "sourceId": 3,
                    "sourceName": "Chilli_Axe",
                }
            ]
        }

    result = high_res.find_matching_backside_candidate(
        front_candidate,
        back_context,
        "https://mpcfill.com/",
        fetch_json=fake_fetch_json,
    )

    assert result is not None
    assert result.identifier == "back123"
    assert seen_payloads[0]["searchSettings"]["sourceSettings"]["sources"] == [[3, True]]


def test_apply_high_res_candidate_invalidates_cached_outputs(tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"
    nested_crop_dir = crop_dir / "vibrance"
    image_dir.mkdir()
    crop_dir.mkdir()
    nested_crop_dir.mkdir()

    card_name = "scryfall_eld_59_opt.png"
    candidate = high_res.HighResCandidate(
        identifier="drive123",
        name="Opt",
        dpi=1200,
        extension="png",
        download_link="https://download/opt.png",
        small_thumbnail_url="https://thumb/small",
        medium_thumbnail_url="https://thumb/medium",
        source_id=7,
        source_name="Test Source",
    )

    (crop_dir / card_name).write_bytes(b"old-crop")
    (nested_crop_dir / card_name).write_bytes(b"old-vibrance-crop")
    img_cache_path = tmp_path / "img.cache"
    img_cache_path.write_text(json.dumps({card_name: {"data": "stale"}}))
    print_dict = {
        "high_res_front_overrides": {},
        "img_cache": str(img_cache_path),
    }

    high_res.apply_high_res_candidate(
        print_dict,
        str(image_dir),
        card_name,
        candidate,
        fetch_bytes=lambda _url: VALID_PNG_BYTES,
    )

    assert not (crop_dir / card_name).exists()
    assert not (nested_crop_dir / card_name).exists()
    assert card_name not in json.loads(img_cache_path.read_text())


def test_apply_high_res_candidate_replaces_matching_backside(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    front_name = "scryfall_mid_1_delver-of-secrets.png"
    back_name = "__scryfall_mid_1_insectile-aberration.png"
    candidate = high_res.HighResCandidate(
        identifier="front123",
        name="Delver of Secrets",
        dpi=800,
        extension="png",
        download_link="https://download/front.png",
        small_thumbnail_url="https://thumb/front-small",
        medium_thumbnail_url="https://thumb/front-medium",
        source_id=3,
        source_name="Chilli_Axe",
    )
    backside_candidate = high_res.HighResCandidate(
        identifier="back123",
        name="Insectile Aberration",
        dpi=800,
        extension="png",
        download_link="https://download/back.png",
        small_thumbnail_url="https://thumb/back-small",
        medium_thumbnail_url="https://thumb/back-medium",
        source_id=3,
        source_name="Chilli_Axe",
    )
    print_dict = {"high_res_front_overrides": {}}
    seen_urls = []

    high_res.apply_high_res_candidate(
        print_dict,
        str(image_dir),
        front_name,
        candidate,
        backside_match=high_res.BacksideMatch(
            filename=back_name,
            candidate=backside_candidate,
        ),
        fetch_bytes=lambda url: seen_urls.append(url) or VALID_PNG_BYTES,
    )

    assert (image_dir / front_name).read_bytes() == VALID_PNG_BYTES
    assert (image_dir / back_name).read_bytes() == VALID_PNG_BYTES
    assert seen_urls == [
        "https://download/front.png",
        "https://download/back.png",
    ]
    assert print_dict["high_res_front_overrides"][front_name]["back_identifier"] == "back123"


def test_apply_high_res_candidate_does_not_overwrite_front_when_download_is_invalid(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    card_name = "scryfall_eld_59_opt.png"
    original_bytes = b"original-front"
    (image_dir / card_name).write_bytes(original_bytes)
    candidate = high_res.HighResCandidate(
        identifier="drive123",
        name="Opt",
        dpi=1200,
        extension="png",
        download_link="https://download/opt.png",
        small_thumbnail_url="https://thumb/small",
        medium_thumbnail_url="https://thumb/medium",
        source_id=7,
        source_name="Test Source",
    )

    try:
        high_res.apply_high_res_candidate(
            {"high_res_front_overrides": {}},
            str(image_dir),
            card_name,
            candidate,
            fetch_bytes=lambda _url: b"<html>bad payload</html>",
            fetch_text=lambda _url: "not-base64-image-data",
        )
    except ValueError as exc:
        assert "valid image file" in str(exc)
    else:
        raise AssertionError("Expected apply_high_res_candidate to fail")

    assert (image_dir / card_name).read_bytes() == original_bytes


def test_apply_high_res_candidate_does_not_overwrite_either_side_if_back_download_is_invalid(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    front_name = "scryfall_mid_1_delver-of-secrets.png"
    back_name = "__scryfall_mid_1_insectile-aberration.png"
    original_front = b"original-front"
    original_back = b"original-back"
    (image_dir / front_name).write_bytes(original_front)
    (image_dir / back_name).write_bytes(original_back)
    candidate = high_res.HighResCandidate(
        identifier="front123",
        name="Delver of Secrets",
        dpi=800,
        extension="png",
        download_link="https://download/front.png",
        small_thumbnail_url="https://thumb/front-small",
        medium_thumbnail_url="https://thumb/front-medium",
        source_id=3,
        source_name="Chilli_Axe",
    )
    backside_candidate = high_res.HighResCandidate(
        identifier="back123",
        name="Insectile Aberration",
        dpi=800,
        extension="png",
        download_link="https://download/back.png",
        small_thumbnail_url="https://thumb/back-small",
        medium_thumbnail_url="https://thumb/back-medium",
        source_id=3,
        source_name="Chilli_Axe",
    )

    def fake_fetch_bytes(url):
        if url.endswith("/front.png"):
            return VALID_PNG_BYTES
        return b"<html>bad back</html>"

    try:
        high_res.apply_high_res_candidate(
            {"high_res_front_overrides": {}},
            str(image_dir),
            front_name,
            candidate,
            backside_match=high_res.BacksideMatch(
                filename=back_name,
                candidate=backside_candidate,
            ),
            fetch_bytes=fake_fetch_bytes,
            fetch_text=lambda _url: "not-base64-image-data",
        )
    except ValueError as exc:
        assert "valid image file" in str(exc)
    else:
        raise AssertionError("Expected double-faced apply to fail")

    assert (image_dir / front_name).read_bytes() == original_front
    assert (image_dir / back_name).read_bytes() == original_back
