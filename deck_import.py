import json
import os
import re
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable


PRINT_FN = Callable[[str], None]

SECTION_HEADERS = {
    "deck",
    "sideboard",
    "commander",
    "companions",
    "companion",
    "maybeboard",
}

LINE_PATTERN = re.compile(
    r"^(?:(?:SB|MB|CMDR|COMMANDER):\s*)?(?P<count>\d+)\s+(?P<name>.+?)"
    r"(?:\s+\((?P<set_code>[A-Za-z0-9]+)\)(?:\s+(?P<collector_number>[A-Za-z0-9]+))?)?$"
)


@dataclass(frozen=True)
class DeckEntry:
    count: int
    name: str
    set_code: str | None = None
    collector_number: str | None = None


@dataclass(frozen=True)
class ImportedCard:
    entry: DeckEntry
    filename: str


@dataclass
class ImportResult:
    imported: list[ImportedCard]
    unmatched_lines: list[str]
    failed_cards: list[str]

    @property
    def imported_count(self) -> int:
        return sum(card.entry.count for card in self.imported)


def parse_decklist(deck_text: str) -> tuple[list[DeckEntry], list[str]]:
    aggregated: OrderedDict[tuple[str, str | None, str | None], DeckEntry] = OrderedDict()
    unmatched_lines: list[str] = []

    for raw_line in deck_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().rstrip(":") in SECTION_HEADERS:
            continue

        match = LINE_PATTERN.match(line)
        if match is None:
            unmatched_lines.append(line)
            continue

        count = int(match.group("count"))
        name = _normalize_card_name(match.group("name"))
        set_code = match.group("set_code")
        collector_number = match.group("collector_number")
        key = (name.casefold(), set_code.lower() if set_code else None, collector_number)

        if key in aggregated:
            previous = aggregated[key]
            aggregated[key] = DeckEntry(
                count=previous.count + count,
                name=previous.name,
                set_code=previous.set_code,
                collector_number=previous.collector_number,
            )
        else:
            aggregated[key] = DeckEntry(
                count=count,
                name=name,
                set_code=set_code.lower() if set_code else None,
                collector_number=collector_number,
            )

    return list(aggregated.values()), unmatched_lines


def import_decklist(
    deck_text: str,
    image_dir: str,
    print_fn: PRINT_FN | None = None,
    fetch_json: Callable[[str], dict] | None = None,
    fetch_bytes: Callable[[str], bytes] | None = None,
) -> ImportResult:
    print_fn = print_fn if print_fn is not None else lambda _text: None
    fetch_json = fetch_json if fetch_json is not None else _fetch_json
    fetch_bytes = fetch_bytes if fetch_bytes is not None else _fetch_bytes

    entries, unmatched_lines = parse_decklist(deck_text)
    imported: list[ImportedCard] = []
    failed_cards: list[str] = []

    for index, entry in enumerate(entries, start=1):
        label = f"{entry.name} ({index}/{len(entries)})"
        print_fn(f"Importing decklist...\nResolving {label}")
        try:
            card_data = resolve_card(entry, fetch_json)
            image_url = extract_image_url(card_data)
            if image_url is None:
                raise ValueError("No downloadable image URL found")

            filename = build_image_filename(card_data)
            print_fn(f"Importing decklist...\nDownloading {label}")
            image_bytes = fetch_bytes(image_url)
            write_downloaded_image(image_dir, filename, image_bytes)
            imported.append(ImportedCard(entry=entry, filename=filename))
        except Exception:
            failed_cards.append(_format_failed_card(entry))

    return ImportResult(
        imported=imported,
        unmatched_lines=unmatched_lines,
        failed_cards=failed_cards,
    )


def apply_imported_counts(print_dict: dict, imported_cards: list[ImportedCard]):
    for imported_card in imported_cards:
        print_dict["cards"][imported_card.filename] = imported_card.entry.count


def read_decklist_file(path: str) -> str:
    with open(path, "rb") as fp:
        raw = fp.read()

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def resolve_card(entry: DeckEntry, fetch_json: Callable[[str], dict]) -> dict:
    if entry.set_code and entry.collector_number:
        url = (
            "https://api.scryfall.com/cards/"
            f"{urllib.parse.quote(entry.set_code)}/{urllib.parse.quote(entry.collector_number)}"
        )
        return fetch_json(url)

    if entry.set_code:
        query = f'!"{entry.name}" set:{entry.set_code}'
        url = "https://api.scryfall.com/cards/search?" + urllib.parse.urlencode(
            {"q": query, "unique": "prints"}
        )
        payload = fetch_json(url)
        if payload.get("object") == "list" and payload.get("data"):
            return payload["data"][0]
        raise ValueError("Card not found")

    url = "https://api.scryfall.com/cards/named?" + urllib.parse.urlencode(
        {"exact": entry.name}
    )
    return fetch_json(url)


def extract_image_url(card_data: dict) -> str | None:
    image_uris = card_data.get("image_uris")
    if image_uris:
        return image_uris.get("png") or image_uris.get("large") or image_uris.get("normal")

    for face in card_data.get("card_faces", []):
        image_uris = face.get("image_uris")
        if image_uris:
            return image_uris.get("png") or image_uris.get("large") or image_uris.get("normal")
    return None


def build_image_filename(card_data: dict) -> str:
    name = card_data.get("name", "card")
    if "//" in name:
        name = name.split("//", 1)[0].strip()

    set_code = (card_data.get("set") or "unknown").lower()
    collector_number = str(card_data.get("collector_number") or "0")
    slug = slugify_filename(name)
    return f"scryfall_{set_code}_{collector_number}_{slug}.png"


def slugify_filename(value: str) -> str:
    slug = value.replace("//", " ")
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.ASCII)
    slug = re.sub(r"[-\s]+", "-", slug.strip(), flags=re.ASCII)
    return slug.lower() or "card"


def write_downloaded_image(image_dir: str, filename: str, image_bytes: bytes):
    os.makedirs(image_dir, exist_ok=True)
    path = os.path.join(image_dir, filename)
    with open(path, "wb") as fp:
        fp.write(image_bytes)


def _normalize_card_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip())
    normalized = normalized.replace(" / ", " // ")
    return normalized


def _format_failed_card(entry: DeckEntry) -> str:
    detail = entry.name
    if entry.set_code:
        detail += f" ({entry.set_code})"
    if entry.collector_number:
        detail += f" {entry.collector_number}"
    return detail


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "print-proxy-prep/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("object") == "error":
        raise ValueError(payload.get("details", "Scryfall error"))
    return payload


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "print-proxy-prep/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()
