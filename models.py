from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from config import CFG
from constants import page_sizes


def _coerce_plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class RenderSettings:
    pagesize: str = "Letter"
    extended_guides: bool = True
    orient: str = "Portrait"
    bleed_edge: str = "0"
    filename: str = "_printme"

    @classmethod
    def default(cls) -> "RenderSettings":
        default_page_size = CFG.DefaultPageSize
        return cls(
            pagesize=default_page_size if default_page_size in page_sizes else "Letter",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "RenderSettings":
        data = data or {}
        default = cls.default()
        return cls(
            pagesize=str(data.get("pagesize", default.pagesize)),
            extended_guides=bool(data.get("extended_guides", default.extended_guides)),
            orient=str(data.get("orient", default.orient)),
            bleed_edge=str(data.get("bleed_edge", default.bleed_edge)),
            filename=str(data.get("filename", default.filename)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pagesize": self.pagesize,
            "extended_guides": self.extended_guides,
            "orient": self.orient,
            "bleed_edge": self.bleed_edge,
            "filename": self.filename,
        }


@dataclass
class CardMetadata:
    name: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    _include_name: bool = False
    _include_set_code: bool = False
    _include_collector_number: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "CardMetadata":
        raw_data = dict(data or {})
        return cls(
            name=_optional_str(raw_data.pop("name", None)),
            set_code=_optional_str(raw_data.pop("set_code", None)),
            collector_number=_optional_str(raw_data.pop("collector_number", None)),
            extras=raw_data,
            _include_name="name" in (data or {}),
            _include_set_code="set_code" in (data or {}),
            _include_collector_number="collector_number" in (data or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.extras)
        if self._include_name or self.name is not None:
            result["name"] = self.name
        if self._include_set_code or self.set_code is not None:
            result["set_code"] = self.set_code
        if self._include_collector_number or self.collector_number is not None:
            result["collector_number"] = self.collector_number
        return result


@dataclass
class HighResOverride:
    identifier: str | None = None
    name: str | None = None
    dpi: int | None = None
    extension: str | None = None
    download_link: str | None = None
    source_id: int | None = None
    source_name: str | None = None
    small_thumbnail_url: str | None = None
    medium_thumbnail_url: str | None = None
    back_identifier: str | None = None
    back_download_link: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "HighResOverride":
        data = dict(data or {})
        dpi = data.pop("dpi", None)
        source_id = data.pop("source_id", None)
        return cls(
            identifier=_optional_str(data.pop("identifier", None)),
            name=_optional_str(data.pop("name", None)),
            dpi=_optional_int(dpi),
            extension=_optional_str(data.pop("extension", None)),
            download_link=_optional_str(data.pop("download_link", None)),
            source_id=_optional_int(source_id),
            source_name=_optional_str(data.pop("source_name", None)),
            small_thumbnail_url=_optional_str(data.pop("small_thumbnail_url", None)),
            medium_thumbnail_url=_optional_str(data.pop("medium_thumbnail_url", None)),
            back_identifier=_optional_str(data.pop("back_identifier", None)),
            back_download_link=_optional_str(data.pop("back_download_link", None)),
            extras=data,
        )

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.extras)
        fields = {
            "identifier": self.identifier,
            "name": self.name,
            "dpi": self.dpi,
            "extension": self.extension,
            "download_link": self.download_link,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "small_thumbnail_url": self.small_thumbnail_url,
            "medium_thumbnail_url": self.medium_thumbnail_url,
            "back_identifier": self.back_identifier,
            "back_download_link": self.back_download_link,
        }
        for key, value in fields.items():
            if value is not None:
                result[key] = value
        return result


@dataclass
class ProjectState:
    image_dir: str = "images"
    img_cache: str = "img.cache"
    cards: dict[str, int] = field(default_factory=dict)
    backside_enabled: bool = False
    backside_default: str = "__back.png"
    backside_offset: str = "0"
    backsides: dict[str, str] = field(default_factory=dict)
    backside_short_edge: dict[str, bool] = field(default_factory=dict)
    oversized_enabled: bool = False
    oversized: dict[str, bool] = field(default_factory=dict)
    card_metadata_store: dict[str, CardMetadata] = field(default_factory=dict)
    high_res_front_overrides_store: dict[str, HighResOverride] = field(default_factory=dict)
    render: RenderSettings = field(default_factory=RenderSettings.default)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ProjectState":
        data = dict(data or {})
        return cls(
            image_dir=str(data.get("image_dir", "images")),
            img_cache=str(data.get("img_cache", "img.cache")),
            cards=_coerce_plain_dict(data.get("cards")),
            backside_enabled=bool(data.get("backside_enabled", False)),
            backside_default=str(data.get("backside_default", "__back.png")),
            backside_offset=str(data.get("backside_offset", "0")),
            backsides=_coerce_plain_dict(data.get("backsides")),
            backside_short_edge=_coerce_plain_dict(data.get("backside_short_edge")),
            oversized_enabled=bool(data.get("oversized_enabled", False)),
            oversized=_coerce_plain_dict(data.get("oversized")),
            card_metadata_store={
                str(key): CardMetadata.from_dict(value)
                for key, value in _coerce_plain_dict(data.get("card_metadata")).items()
            },
            high_res_front_overrides_store={
                str(key): HighResOverride.from_dict(value)
                for key, value in _coerce_plain_dict(data.get("high_res_front_overrides")).items()
            },
            render=RenderSettings.from_dict(data),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "image_dir": self.image_dir,
            "img_cache": self.img_cache,
            "cards": dict(self.cards),
            "backside_enabled": self.backside_enabled,
            "backside_default": self.backside_default,
            "backside_offset": self.backside_offset,
            "backsides": dict(self.backsides),
            "backside_short_edge": dict(self.backside_short_edge),
            "oversized_enabled": self.oversized_enabled,
            "oversized": dict(self.oversized),
            "card_metadata": self.card_metadata_dict(),
            "high_res_front_overrides": self.high_res_front_overrides_dict(),
        }
        result.update(self.render.to_dict())
        return result

    @property
    def pagesize(self) -> str:
        return self.render.pagesize

    @pagesize.setter
    def pagesize(self, value: str) -> None:
        self.render.pagesize = str(value)

    @property
    def extended_guides(self) -> bool:
        return self.render.extended_guides

    @extended_guides.setter
    def extended_guides(self, value: Any) -> None:
        self.render.extended_guides = bool(value)

    @property
    def orient(self) -> str:
        return self.render.orient

    @orient.setter
    def orient(self, value: str) -> None:
        self.render.orient = str(value)

    @property
    def bleed_edge(self) -> str:
        return self.render.bleed_edge

    @bleed_edge.setter
    def bleed_edge(self, value: Any) -> None:
        self.render.bleed_edge = str(value)

    @property
    def filename(self) -> str:
        return self.render.filename

    @filename.setter
    def filename(self, value: str) -> None:
        self.render.filename = str(value)

    def copy_from(self, other: "ProjectState") -> None:
        replacement = ProjectState.from_dict(other.to_dict())
        self.image_dir = replacement.image_dir
        self.img_cache = replacement.img_cache
        self.cards = replacement.cards
        self.backside_enabled = replacement.backside_enabled
        self.backside_default = replacement.backside_default
        self.backside_offset = replacement.backside_offset
        self.backsides = replacement.backsides
        self.backside_short_edge = replacement.backside_short_edge
        self.oversized_enabled = replacement.oversized_enabled
        self.oversized = replacement.oversized
        self.card_metadata_store = replacement.card_metadata_store
        self.high_res_front_overrides_store = replacement.high_res_front_overrides_store
        self.render = replacement.render

    def get_card_count(self, card_name: str, default: int = 0) -> int:
        return int(self.cards.get(card_name, default))

    def set_card_count(self, card_name: str, count: int) -> None:
        self.cards[card_name] = int(count)

    def remove_card(self, card_name: str) -> None:
        self.cards.pop(card_name, None)
        self.backsides.pop(card_name, None)
        self.backside_short_edge.pop(card_name, None)
        self.oversized.pop(card_name, None)
        self.card_metadata_store.pop(card_name, None)
        self.high_res_front_overrides_store.pop(card_name, None)

    def card_metadata_dict(self) -> dict[str, dict[str, Any]]:
        return {
            key: value.to_dict()
            for key, value in self.card_metadata_store.items()
        }

    def get_card_metadata(self, card_name: str) -> dict[str, Any] | None:
        metadata = self.card_metadata_store.get(card_name)
        return None if metadata is None else metadata.to_dict()

    def set_card_metadata(self, card_name: str, metadata: Mapping[str, Any] | CardMetadata) -> None:
        if isinstance(metadata, CardMetadata):
            self.card_metadata_store[card_name] = metadata
        else:
            self.card_metadata_store[card_name] = CardMetadata.from_dict(metadata)

    def high_res_front_overrides_dict(self) -> dict[str, dict[str, Any]]:
        return {
            key: value.to_dict()
            for key, value in self.high_res_front_overrides_store.items()
        }

    def get_high_res_override(self, card_name: str) -> dict[str, Any] | None:
        override = self.high_res_front_overrides_store.get(card_name)
        return None if override is None else override.to_dict()

    def set_high_res_override(
        self,
        card_name: str,
        override: Mapping[str, Any] | HighResOverride,
    ) -> None:
        if isinstance(override, HighResOverride):
            self.high_res_front_overrides_store[card_name] = override
        else:
            self.high_res_front_overrides_store[card_name] = HighResOverride.from_dict(override)

    def set_backside(self, front_name: str, back_name: str) -> None:
        self.backside_enabled = True
        self.backsides[front_name] = back_name

    def clear_card_links(self, card_name: str) -> None:
        self.backsides.pop(card_name, None)
        self.backside_short_edge.pop(card_name, None)
        self.oversized.pop(card_name, None)

    def apply_imported_card(
        self,
        filename: str,
        count: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.set_card_count(filename, count)
        if metadata is not None:
            self.set_card_metadata(filename, metadata)

    def remove_missing_cards(self, valid_names: set[str]) -> None:
        for card_name in list(self.cards):
            if card_name not in valid_names:
                self.remove_card(card_name)

    def ensure_card_defaults(self, card_names: list[str]) -> None:
        for card_name in card_names:
            if card_name not in self.cards:
                self.cards[card_name] = 0 if card_name.startswith("__") else 1


def as_project_state(project_like: ProjectState | Mapping[str, Any] | None) -> ProjectState:
    if isinstance(project_like, ProjectState):
        return project_like
    return ProjectState.from_dict(project_like)


def project_to_dict(project_like: ProjectState | Mapping[str, Any]) -> dict[str, Any]:
    return as_project_state(project_like).to_dict()
