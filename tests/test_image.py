import image


def test_is_pre_cropped_image_name_detects_scryfall_prefix():
    assert image.is_pre_cropped_image_name("scryfall_moc_166_card-name.png") is True
    assert image.is_pre_cropped_image_name("card-a.png") is False


def test_effective_dpi_from_dimensions_uses_card_frame_type():
    regular_dpi = image.effective_dpi_from_dimensions(816, 1110, "card-a.png")
    scryfall_dpi = image.effective_dpi_from_dimensions(
        744, 1038, "scryfall_moc_166_card-name.png"
    )

    assert round(regular_dpi) == 300
    assert round(scryfall_dpi) == 300


def test_cropper_skips_crop_for_scryfall_images(monkeypatch, tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"
    image_dir.mkdir()
    crop_dir.mkdir()
    (image_dir / "scryfall_moc_166_card-name.png").write_bytes(b"stub")

    writes = []
    crop_calls = []

    monkeypatch.setattr(image, "list_image_files", lambda folder: ["scryfall_moc_166_card-name.png"])
    monkeypatch.setattr(image, "read_image", lambda path: "raw-image")
    monkeypatch.setattr(
        image,
        "write_image",
        lambda path, data: writes.append((path, data)),
    )
    monkeypatch.setattr(
        image,
        "crop_image",
        lambda *args, **kwargs: crop_calls.append(args) or "cropped-image",
    )
    monkeypatch.setattr(image, "need_cache_previews", lambda crop_dir_arg, img_dict: False)

    messages = []
    image.cropper(
        str(image_dir),
        str(crop_dir),
        str(tmp_path / "img.cache"),
        {},
        bleed_edge=None,
        max_dpi=None,
        do_vibrance_bump=False,
        uncrop=False,
        print_fn=messages.append,
    )

    assert crop_calls == []
    assert writes == [(str(crop_dir / "scryfall_moc_166_card-name.png"), "raw-image")]
    assert any("Skipping crop for pre-cropped image" in message for message in messages)


def test_cropper_still_crops_non_scryfall_images(monkeypatch, tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"
    image_dir.mkdir()
    crop_dir.mkdir()
    (image_dir / "card-a.png").write_bytes(b"stub")

    writes = []
    crop_calls = []

    monkeypatch.setattr(image, "list_image_files", lambda folder: ["card-a.png"])
    monkeypatch.setattr(image, "read_image", lambda path: "raw-image")
    monkeypatch.setattr(
        image,
        "write_image",
        lambda path, data: writes.append((path, data)),
    )
    monkeypatch.setattr(
        image,
        "crop_image",
        lambda *args, **kwargs: crop_calls.append(args) or "cropped-image",
    )
    monkeypatch.setattr(image, "need_cache_previews", lambda crop_dir_arg, img_dict: False)

    image.cropper(
        str(image_dir),
        str(crop_dir),
        str(tmp_path / "img.cache"),
        {},
        bleed_edge=None,
        max_dpi=None,
        do_vibrance_bump=False,
        uncrop=False,
        print_fn=lambda _message: None,
    )

    assert len(crop_calls) == 1
    assert writes == [(str(crop_dir / "card-a.png"), "cropped-image")]
