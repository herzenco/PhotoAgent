# PhotoAgent — Project Status & Handoff Document

**Date:** April 2, 2026
**Prepared for:** Lupe (assistant)
**Prepared by:** Herzen + Claude

---

## What Is PhotoAgent?

PhotoAgent is a **local-first, privacy-focused CLI tool** that scans image libraries on any mounted drive (including external SSDs), understands the content of every image using local AI models, and reorganizes/renames files based on natural language instructions.

**Core privacy principle:** No image ever leaves the user's machine. All vision processing happens locally. Only plain-text metadata (filenames, tags, captions) is sent to the Claude API for organization planning.

---

## What Was Built (Phases 1-5)

### Phase 1: File Scanner + EXIF Extraction
- **`photoagent scan <path>`** — Walks any directory (including mounted SSDs), finds all image files, extracts EXIF metadata (camera, GPS, dates, settings), reverse geocodes GPS coordinates to city/country (offline), computes MD5 and perceptual hashes for duplicate detection, and stores everything in a SQLite database at `<path>/.photoagent/catalog.db`.
- **`photoagent status <path>`** — Shows catalog statistics: total images, analyzed count, yearly breakdown, camera breakdown, top locations, disk usage, duplicates, screenshots.
- Supports incremental scanning — re-running `scan` only processes new/modified files.
- Supports: JPG, JPEG, PNG, HEIC, HEIF, WEBP, GIF, TIFF, BMP, RAW, CR2, NEF, ARW.

### Phase 2: Local Vision Analysis Pipeline
- **`photoagent analyze <path>`** — Runs AI analysis on all scanned images, entirely on the local machine.
- Four analysis modules that run sequentially (models loaded/unloaded one at a time to stay under 2GB RAM):
  1. **Quality Assessor** — Blur detection (Laplacian variance), exposure analysis, resolution check, screenshot detection (phone aspect ratios + status bar heuristics).
  2. **CLIP Tagger** — OpenCLIP ViT-B/32 model classifies images against ~200 labels (scenes, content, activities, people). Stores top-10 tags per image.
  3. **Image Captioner** — Florence-2 model generates captions on GPU; on CPU, automatically falls back to constructing captions from CLIP tags (much faster).
  4. **Face Detector** — InsightFace/ArcFace detects faces, extracts 512-dim embeddings, clusters with DBSCAN to group the same person across photos.
- Flags: `--lite` (CLIP + quality only, fastest), `--skip-captions`, `--device cpu/cuda/mps`.
- Resumable — if interrupted, picks up where it left off.

### Phase 3: Organization Planner (Claude API)
- **`photoagent organize <path> "instruction"`** — Takes a natural language instruction like *"Sort beach photos by year, put screenshots in their own folder"*.
- Builds a **text-only** catalog summary (tags, captions, dates, locations, face clusters — never pixel data) and sends it to Claude Sonnet.
- Claude returns a JSON plan mapping each image to its new path.
- **Privacy guards enforced in code:**
  - Regex assertion blocks any base64 strings (100+ chars) in the payload.
  - Binary magic byte detection (JPEG, PNG, GIF, WebP headers).
  - Payload size limit (10MB max).
  - `--verbose` flag logs every outbound API request body so the user can verify.
- For large libraries (>5000 images), the manifest is chunked across multiple API calls. Each subsequent chunk receives the folder structure from prior chunks to maintain naming consistency.
- Displays the plan as a rich tree view + move table for user approval before executing.
- Default is `--dry-run` (preview only).

### Phase 4: Execution Engine + Undo System
- **Safe file execution** — After the user approves a plan:
  1. Writes a manifest JSON to `<path>/.photoagent/manifests/` BEFORE touching any files.
  2. For each move: COPIES to destination, verifies MD5 match, only then deletes source.
  3. Handles filename conflicts with `_001`, `_002` suffixes.
  4. Updates the SQLite catalog with new paths.
  5. Per-file error isolation — one failure doesn't stop the batch.
- **`photoagent undo <path>`** — Reverses the last operation using the manifest. Same copy-verify-delete safety.
- **`photoagent history <path>`** — Shows all past operations with timestamps, instructions, and status.

### Phase 5: Search, Templates, Export & More
- **`photoagent search <path> "query"`** — Text-based search across tags, captions, filenames, locations. Supports filters: `--year`, `--location`, `--min-quality`, `--type photo/screenshot`, `--camera`, `--person`.
- **`photoagent organize-template <path> --template <name>`** — Offline organization (zero network access):
  - `by-date` — `Year/Month/filename.jpg`
  - `by-date-location` — `Year/Month/Location/filename.jpg`
  - `by-camera` — `Camera Model/filename.jpg`
  - `by-type` — Separates Photos / Screenshots / Duplicates / Low Quality
  - `cleanup` — Moves duplicates and low-quality images to a Review folder
  - `--yaml custom.yaml` — User-defined rules with match conditions and template variables
- **`photoagent export-catalog <path>`** — Export catalog as JSON or CSV. Supports `--format csv`, filters.
- **`photoagent config`** — Manage API key (stored in system keyring), default device, default template.
- **`photoagent rename-person <path> <cluster_id> "Name"`** — Assign real names to face clusters.
- **`photoagent list-people <path>`** — Show all detected face clusters with photo counts.

---

## All CLI Commands

| Command | Phase | Status | Needs API Key? |
|---|---|---|---|
| `photoagent scan <path>` | 1 | Working | No |
| `photoagent status <path>` | 1 | Working | No |
| `photoagent analyze <path>` | 2 | Working | No |
| `photoagent organize <path> "instruction"` | 3 | Working | **Yes** |
| `photoagent undo <path>` | 4 | Working | No |
| `photoagent history <path>` | 4 | Working | No |
| `photoagent search <path> "query"` | 5 | Working | No |
| `photoagent organize-template <path> --template name` | 5 | Working | No |
| `photoagent export-catalog <path>` | 5 | Working | No |
| `photoagent config` | 5 | Working | No |
| `photoagent rename-person <path> <id> "name"` | 5 | Working | No |
| `photoagent list-people <path>` | 5 | Working | No |

---

## Test Suite

- **182 tests passing, 1 skipped** (GPS reverse geocode fixture edge case)
- Tests cover: database CRUD, file scanning, EXIF extraction, hashing, quality assessment, screenshot detection, CLI commands, privacy guards (critical), plan display, execution safety, undo integrity, search, templates, export, face management, config.
- Run with: `source .venv/bin/activate && python -m pytest tests/ -v`

---

## Project Structure

```
PhotoAgent/
├── pyproject.toml                    # Project metadata + dependencies
├── photoagent-build-plan.md          # Original build plan (6 phases)
├── project-status.md                 # This file
├── .gitignore
├── src/photoagent/
│   ├── __init__.py                   # Version
│   ├── cli.py                        # Typer app — all 12 commands
│   ├── database.py                   # SQLite catalog (images, faces, duplicates, operations tables)
│   ├── models.py                     # Dataclasses (ImageRecord, ScanResult, AnalysisResult, ExecutionResult, etc.)
│   ├── scanner.py                    # os.scandir-based file walker, incremental scan
│   ├── exif.py                       # EXIF extraction + GPS reverse geocoding
│   ├── hashing.py                    # MD5 + perceptual hash
│   ├── scan_cli.py                   # Rich progress bar wiring for scan
│   ├── analyze_cli.py                # Rich progress bar wiring for analyze
│   ├── summarizer.py                 # Builds text-only catalog summaries for the API
│   ├── planner.py                    # Claude API client + privacy guards + plan chunking
│   ├── plan_display.py               # Rich tree/table plan preview + approval UI
│   ├── organize_cli.py               # CLI wiring for organize command
│   ├── executor.py                   # Copy-verify-delete execution engine
│   ├── undo.py                       # Undo manager + operation history
│   ├── execute_cli.py                # CLI wiring for undo/history
│   ├── search.py                     # Text + optional CLIP semantic search
│   ├── search_cli.py                 # CLI wiring for search
│   ├── templates.py                  # 5 built-in templates + custom YAML engine
│   ├── template_cli.py               # CLI wiring for template organize
│   ├── export.py                     # JSON/CSV catalog export
│   ├── face_manager.py               # Face cluster listing/renaming
│   ├── config_manager.py             # API key + config management
│   └── vision/
│       ├── __init__.py
│       ├── clip_tagger.py            # OpenCLIP ViT-B/32, ~200 label taxonomy
│       ├── captioner.py              # Florence-2 + CLIP tag fallback
│       ├── quality.py                # Blur/exposure/screenshot detection
│       ├── face_detector.py          # InsightFace + DBSCAN clustering
│       └── pipeline.py               # Sequential model loading orchestrator
└── tests/                            # 182 tests across 17 test files
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12 |
| CLI | Typer + Rich |
| Database | SQLite (WAL mode, foreign keys) |
| EXIF | exifread + pillow-heif |
| Geocoding | reverse_geocoder (offline) |
| Hashing | imagehash + hashlib |
| Vision — Tagging | OpenCLIP ViT-B/32 |
| Vision — Captioning | Florence-2 (GPU) / CLIP tag fallback (CPU) |
| Vision — Faces | InsightFace ArcFace + DBSCAN |
| Vision — Quality | Pillow + numpy heuristics |
| LLM | Anthropic Claude Sonnet (text only) |
| Config | keyring (system keychain) |

---

## Current State of Herzen's SSD Test

- Scanned **174 images** (1 GB) from `/Volumes/BACKUP/PHOTOAGENT TEST`
- Cameras detected: **Fuji X100V** (82 photos), **Canon EOS R8** (25), **Canon EOS RP** (6), **DJI drone** (1)
- Location detected: **Banner Elk, US** (3 photos with GPS)
- **5 screenshots** detected
- **116 images missing date_taken** — likely RAW files where EXIF date parsing needs improvement
- Already analyzed with `--lite` mode (CLIP tagging + quality assessment)
- Catalog stored at `/Volumes/BACKUP/PHOTOAGENT TEST/.photoagent/catalog.db`

---

## Known Issues / TODO

1. **RAW file EXIF dates** — 116 of 174 images have no `date_taken`. The EXIF extractor uses `exifread` which handles most formats, but some RAW files (especially Fuji RAF) may need additional parsing. Could add `rawpy` for better RAW support.

2. **Phase 6 not built** — The Tauri desktop UI (Phase 6 in the build plan) was not started. This is the optional "product launch" phase — a cross-platform desktop app wrapping the CLI.

3. **CLIP embeddings not stored for vector search** — The build plan called for `sqlite-vss` or `chromadb` for efficient embedding storage. Currently CLIP embeddings are computed but not persisted, so semantic search falls back to text matching only.

4. **No `pyyaml` in pyproject.toml** — The template engine uses PyYAML for custom templates, but it's not listed in the dependencies (installed manually). Should be added.

---

## How to Run

```bash
cd ~/Desktop/PhotoAgent
source .venv/bin/activate

# Scan photos
photoagent scan "/Volumes/BACKUP/PHOTOAGENT TEST"

# Check status
photoagent status "/Volumes/BACKUP/PHOTOAGENT TEST"

# Analyze (lite = fast, no GPU needed)
photoagent analyze "/Volumes/BACKUP/PHOTOAGENT TEST" --lite

# Search
photoagent search "/Volumes/BACKUP/PHOTOAGENT TEST" "sunset"

# Organize by template (offline, no API key)
photoagent organize-template "/Volumes/BACKUP/PHOTOAGENT TEST" --template by-camera

# Organize with AI (needs API key)
photoagent config --set-api-key sk-ant-xxx
photoagent organize "/Volumes/BACKUP/PHOTOAGENT TEST" "Sort by year and location"

# Run tests
python -m pytest tests/ -v
```

---

## GitHub

Repository: https://github.com/herzenco/PhotoAgent
Branch: `main`
Latest commit includes all Phases 1-5 (51 files, ~12,000 lines of code).
