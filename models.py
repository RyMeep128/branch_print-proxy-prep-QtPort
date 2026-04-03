from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, MutableMapping

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

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "CardMetadata":
        data = dict(data or {})
        return cls(
            name=_optional_str(data.pop("name", None)),
            set_code=_optional_str(data.pop("set_code", None)),
            collector_number=_optional_str(data.pop("collector_number", None)),
            extras=data,
        )

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.extras)
        result["name"] = self.name
        result["set_code"] = self.set_code
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


class _DataclassValueMap(MutableMapping[str, dict[str, Any]]):
    def __init__(self, storage: dict[str, Any], parser):
        self._storage = storage
        self._parser = parser

    def __getitem__(self, key: str) -> dict[str, Any]:
        return self._storage[key].to_dict()

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(value, "to_dict"):
            self._storage[key] = value
        else:
            self._storage[key] = self._parser(value)

    def __delitem__(self, key: str) -> None:
        del self._storage[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._storage)

    def __len__(self) -> int:
        return len(self._storage)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {key: value.to_dict() for key, value in self._storage.items()}


@dataclass
class ProjectState(MutableMapping[str, Any]):
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

    _KEY_MAP = {
        "image_dir": "image_dir",
        "img_cache": "img_cache",
        "cards": "cards",
        "backside_enabled": "backside_enabled",
        "backside_default": "backside_default",
        "backside_offset": "backside_offset",
        "backsides": "backsides",
        "backside_short_edge": "backside_short_edge",
        "oversized_enabled": "oversized_enabled",
        "oversized": "oversized",
    }
    _RENDER_KEYS = {"pagesize", "extended_guides", "orient", "bleed_edge", "filename"}

    @property
    def card_metadata(self) -> _DataclassValueMap:
        return _DataclassValueMap(self.card_metadata_store, CardMetadata.from_dict)

    @property
    def high_res_front_overrides(self) -> _DataclassValueMap:
        return _DataclassValueMap(self.high_res_front_overrides_store, HighResOverride.from_dict)

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
            "card_metadata": self.card_metadata.to_dict(),
            "high_res_front_overrides": self.high_res_front_overrides.to_dict(),
        }
        result.update(self.render.to_dict())
        return result

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

    def __getitem__(self, key: str) -> Any:
        if key in self._KEY_MAP:
            return getattr(self, self._KEY_MAP[key])
        if key in self._RENDER_KEYS:
            return getattr(self.render, key)
        if key == "card_metadata":
            return self.card_metadata
        if key == "high_res_front_overrides":
            return self.high_res_front_overrides
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self._KEY_MAP:
            setattr(self, self._KEY_MAP[key], value)
            return
        if key in self._RENDER_KEYS:
            setattr(self.render, key, value)
            return
        if key == "card_metadata":
            self.card_metadata_store = {
                str(item_key): CardMetadata.from_dict(item_value)
                for item_key, item_value in _coerce_plain_dict(value).items()
            }
            return
        if key == "high_res_front_overrides":
            self.high_res_front_overrides_store = {
                str(item_key): HighResOverride.from_dict(item_value)
                for item_key, item_value in _coerce_plain_dict(value).items()
            }
            return
        raise KeyError(key)

    def __delitem__(self, key: str) -> None:
        raise KeyError(f"Top-level project key deletion is not supported: {key}")

    def __iter__(self) -> Iterator[str]:
        yield from [
            "image_dir",
            "img_cache",
            "cards",
            "backside_enabled",
            "backside_default",
            "backside_offset",
            "backsides",
            "backside_short_edge",
            "oversized_enabled",
            "oversized",
            "card_metadata",
            "high_res_front_overrides",
            "pagesize",
            "extended_guides",
            "orient",
            "bleed_edge",
            "filename",
        ]

    def __len__(self) -> int:
        return 17


def as_project_state(project_like: ProjectState | Mapping[str, Any] | None) -> ProjectState:
    if isinstance(project_like, ProjectState):
        return project_like
    return ProjectState.from_dict(project_like)


def sync_project_container(target: ProjectState | MutableMapping[str, Any], state: ProjectState) -> ProjectState:
    if isinstance(target, ProjectState):
        target.copy_from(state)
        return target
    target.clear()
    target.update(state.to_dict())
    return state


def project_to_dict(project_like: ProjectState | Mapping[str, Any]) -> dict[str, Any]:
    return as_project_state(project_like).to_dict()
