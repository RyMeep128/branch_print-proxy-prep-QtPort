# print-proxy-prep
Prepare proxy card images for home printing with a desktop Qt app.

The app can:
- crop bleed edges and build print-ready PDFs
- import card images from Scryfall using pasted decklists, deck files, or public Archidekt URLs
- handle double-faced cards and per-card backsides
- search MPCFill for higher-DPI replacements
- cache previews and high-res search results so repeat work is much faster

![_printme pdf - Adobe Acrobat Reader (64-bit) 2024-09-26 09_49_43](https://github.com/user-attachments/assets/01c0f25e-61a9-4189-8b00-0dfedac6e73d)

# Installation

## Quick Start
- Install the latest Python and make sure `python` is on `PATH`
- Clone or unzip this repo
- Run `Setup Print Proxy Prep.cmd`
- Run `Launch Print Proxy Prep.cmd`
- Optional: run `Create Desktop Shortcut.ps1` once

## Build a Windows App Bundle
If you want to hand this to someone without requiring Python on their machine, run `Build EXE.cmd`.

That produces:
- `dist\Print Proxy Prep\Print Proxy Prep.exe`

## Manual Notes
`Setup Print Proxy Prep.cmd` creates `images`, `images\crop`, a local `venv`, upgrades `pip`, and installs the dependencies from `requirements.txt`.

After setup you can either:
- run `venv\Scripts\python main.py`
- or double-click `Launch Print Proxy Prep.cmd`

The launcher will run setup first if `venv` does not exist yet.

# Running the App

You can start from either direction:
- drop existing card images into `images`
- or use `Import Decklist` to download them from Scryfall

Images whose filenames start with `__` are treated as helper assets and are hidden from the main card list.

## Main Areas

### Card Grid
The left side of the window shows the current cards in a grid.

Each card tile includes:
- the card image
- copy count controls
- a DPI badge showing the current effective DPI
- a warning-style badge when the DPI is below the low-DPI threshold
- optional backside and oversized controls when those features are enabled

Global controls at the top of the grid let you increment, decrement, or reset all visible card counts.

### Preview Tab
The `Preview` tab renders the current document layout so you can sanity-check pagination, bleed, guides, and backsides before exporting.

### Actions Panel
The right-side `Actions` box includes:
- `Run Cropper`
- `Render Document`
- `Save Project`
- `Load Project`
- `Set Image Folder`
- `Open Images`
- `Settings`
- `Import Decklist`
- `Clear Old Cards`

# Importing Cards

## Import Decklist
`Import Decklist` can import from:
- pasted deck text like `4 Lightning Bolt`
- deck files such as `.txt`, `.csv`, `.dek`, `.mtga`, and `.dck`
- CSV rows with `count`, `name`, `set_code`, and `collector_number`
- public Archidekt deck URLs

The importer resolves cards through Scryfall and downloads image files into your image folder.

If a deck contains double-faced cards, the importer also pulls the matching back face and automatically enables per-card backsides for those imports.

If some lines cannot be parsed or some cards cannot be resolved, the app shows a summary instead of silently failing.

## Existing Images
If you already have card art, place it in `images` and run the cropper.

If a file is already pre-cropped, enable `Allow Precropped` in `Settings` and place the file in `images\crop`. The app will treat it as already cropped and keep the rest of the workflow working.

# Printing Options

## Print Options
The print section controls:
- output PDF filename
- paper size
- portrait vs landscape
- extended guides

### Extended Guides
This extends cut guides all the way to the page edge. It uses a little more ink but makes trimming easier.

## Card Options
The card section controls:
- bleed edge
- backside support
- default backside image
- backside print offset
- oversized-card support

### Bleed Edge
Adds a little extra border around each card so slight cutting errors are less visible.

### Backsides
When `Enable Backside` is on, the app generates alternating front and back pages for duplex-style printing.

You can:
- set a global default backside with the `Default` button
- click the mini backside on a card tile to choose a custom backside for that card
- reset a card back to the default
- mark a card as `Sideways` for short-edge flipping

`__back.png` is the default expected card back. If it is missing, the UI falls back to a placeholder image.

### Backside Offset
Use `Offset` if your printer lines up front and back pages with a small horizontal drift.

### Oversized
Turn on `Enable Oversized Option` if some cards need oversized handling, then mark those cards individually in the grid.

# High-Res Replacements

Click any card image in the grid to open the high-res picker.

The high-res flow can:
- search MPCFill-compatible backends for alternate front art
- filter by minimum and maximum DPI
- page through large result sets 60 at a time
- preview thumbnails before applying
- download and apply a selected replacement
- remember the currently selected high-res source for each card

For imported double-faced cards, applying a matching high-res front can also try to find and apply the matching high-res back from the same source.

## Backend Setup
High-res search uses the `HighRes.BackendURL` config value. By default it points at:
- `https://mpcfill.com/`

You can change this from the in-app `Settings` dialog or by editing `config.ini`.

## Caching
High-res search and image previews are cached to keep repeated browsing snappy.

Important cache locations:
- `img.cache` for local thumbnail/preview data
- `.high_res_cache/` for high-res search and image caches

# Settings and Config

Use the `Settings` button to edit app-wide config values such as:
- display columns in the card grid
- allow precropped images
- vibrance bump
- max crop DPI
- default paper size
- high-res backend URL
- high-res cache TTL
- high-res search cache size
- high-res image cache size

These values are stored in `config.ini`.

# Saving and Project Files

The app stores project state in `print.json`, including:
- selected card counts
- backside assignments
- oversized flags
- imported metadata
- high-res override metadata

`Save Project` and `Load Project` let you work with other project JSON files too.

The app also remembers window layout and the last-used project path through Qt settings.

# Render Document

When you are happy with the layout, click `Render Document` and choose where to save the PDF. The app renders the file and then attempts to open it automatically.

# Notes

- If the program crashes on startup, first try deleting `print.json`, `img.cache`, and `.high_res_cache`.
- If you switch to a different image folder, the project and preview caches are rebuilt as needed.
- `Run Cropper` may be required again after changing settings such as `Max DPI` or `Vibrance Bump`.
- If you report a bug, include your `images` folder, `print.json`, `img.cache`, and any helpful repro steps.
