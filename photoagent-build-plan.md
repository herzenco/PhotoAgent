# PhotoAgent — Build Plan

## Local AI-Powered Image Organizer

> **Core Principle:** No image ever leaves the user's machine. All vision processing happens locally. Only plain-text instructions and metadata are sent to cloud LLMs for planning.

---

## Product Summary

PhotoAgent is a local-first CLI tool (with optional desktop UI) that scans a user's image library on any mounted drive (including external SSDs), understands the content of every image using local AI models, and reorganizes/renames files based on natural language instructions.

**Example usage:**

```bash
photoagent scan /Volumes/MySSD/Photos
photoagent analyze
photoagent organize "Sort all beach and vacation photos by year and location. Put screenshots in their own folder. Group photos of people together. Put blurry or dark photos in a Review folder."
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        USER'S MACHINE                       │
│                                                             │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ SSD/Drive│───▶│  File Scanner │───▶│  SQLite Catalog  │   │
│  │ (images) │    │  + EXIF Read  │    │  (all metadata)  │   │
│  └──────────┘    └──────────────┘    └────────┬─────────┘   │
│                                               │             │
│  ┌──────────────────────────────────┐         │             │
│  │  LOCAL Vision Models             │◀────────┘             │
│  │  - CLIP (tagging/classification) │                       │
│  │  - LLaVA / Florence-2 (captions)│─────────┐             │
│  │  - SSIM (duplicate detection)    │         │             │
│  └──────────────────────────────────┘         │             │
│                                               ▼             │
│                                     ┌──────────────────┐    │
│                                     │  Enriched Catalog │    │
│                                     │  (tags, captions, │    │
│                                     │   embeddings)     │    │
│                                     └────────┬─────────┘    │
│                                              │              │
└──────────────────────────────────────────────┼──────────────┘
                                               │
                    ONLY plain-text metadata    │
                    leaves the machine          │
                    (no images, no pixels)      ▼
                                     ┌──────────────────┐
                                     │  Claude API      │
                                     │  (text only)     │
                                     │  - Parse instruct│
                                     │  - Generate plan │
                                     └────────┬─────────┘
                                              │
                    JSON plan returned         │
                    (file paths + destinations)│
                                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        USER'S MACHINE                       │
│                                                             │
│  ┌──────────────────┐    ┌───────────┐    ┌─────────────┐   │
│  │  Plan Viewer      │───▶│  Executor │───▶│  Undo Log   │   │
│  │  (user approves)  │    │  (move/   │    │  (manifest) │   │
│  └──────────────────┘    │  rename)  │    └─────────────┘   │
│                          └───────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Privacy Contract

These rules are non-negotiable and must be enforced in code:

1. **No image bytes are ever transmitted over the network.** Vision analysis is 100% local.
2. **Only text metadata is sent to Claude API** — filenames, EXIF data, AI-generated tags/captions, and the user's natural language instruction. Never thumbnails, never base64, never file contents.
3. **The catalog (SQLite DB) stays on the user's machine.**
4. **All network calls are auditable.** A `--verbose` flag logs every outbound API request body so the user can verify no image data is included.
5. **Offline mode is supported.** If the user provides a predefined organization template instead of free-form instructions, the tool works with zero network access.

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for ML models and CLI tools |
| CLI Framework | Typer | Clean, typed CLI with auto-generated help |
| Database | SQLite via `sqlite3` | Zero setup, portable, fast for this scale |
| EXIF Extraction | `Pillow` + `pillow-heif` + `exifread` | Comprehensive EXIF/IPTC/XMP support, including HEIC/HEIF |
| Reverse Geocoding | `reverse_geocoder` (offline) | GPS → city/country with no network call |
| Local Vision - Tagging | OpenCLIP (`open_clip_torch`) | Fast, accurate image classification and tagging |
| Local Vision - Captioning | `transformers` + Florence-2 or LLaVA | Detailed image descriptions, runs on CPU (slow) or GPU |
| Duplicate Detection | `imagehash` + SSIM via `scikit-image` | Perceptual hashing for near-duplicate finding |
| Face Detection/Clustering | `insightface` (ArcFace) | Local face embedding for people-grouping — no cloud calls |
| Quality Assessment | `Pillow` + custom heuristics | Blur detection (Laplacian variance), exposure analysis |
| Vector Storage | `sqlite-vss` or `chromadb` | Efficient embedding storage and similarity search instead of raw BLOBs |
| LLM (text only) | Anthropic Python SDK (Claude Sonnet) | Instruction parsing and plan generation — text only |
| Terminal UI | `rich` | Progress bars, tables, plan display, confirmations |
| Desktop UI (later) | Tauri (Rust + web frontend) | Lightweight, local-first, cross-platform |

---

## Phase Breakdown

Each phase is designed as an independent Claude Code session. Phases are sequential — each builds on the last. Use Claude Code's multi-agent capabilities to parallelize work within each phase where noted.

---

### Phase 1: Project Scaffolding + File Scanner + EXIF Extraction

**Goal:** A working CLI that scans any mounted drive, catalogs every image, and extracts all free metadata.

**Claude Code Prompt:**

```
Build a Python CLI tool called "photoagent" using Typer. Set up the project with:

- pyproject.toml with all dependencies
- src/photoagent/ package structure
- Entry point: src/photoagent/cli.py

Implement the `scan` command:
  photoagent scan <path> [--recursive] [--extensions jpg,jpeg,png,heic,heif,webp,gif,tiff,bmp,raw,cr2,nef,arw]

Behavior:
1. Validate that <path> exists and is readable (support mounted volumes like /Volumes/MySSD or /mnt/ssd)
2. Walk the directory tree recursively by default
3. For each image file found:
   - Record: absolute path, filename, extension, file size, created/modified timestamps
   - Extract EXIF data using exifread: date taken, GPS coordinates, camera make/model, lens, ISO, aperture, shutter speed, orientation, flash used
   - Use pillow-heif for HEIC/HEIF file support (Pillow does not handle these natively)
   - If GPS coordinates exist, reverse geocode to city/country using the reverse_geocoder library (offline, no network)
   - Compute perceptual hash using imagehash (pHash) for later duplicate detection
   - Compute file MD5 hash for exact duplicate detection
4. Store everything in a SQLite database at <path>/.photoagent/catalog.db
5. Show a rich progress bar during scanning
6. Handle errors gracefully — log unreadable files but continue scanning
7. If catalog.db already exists, only process new/modified files (incremental scan)

Schema for the images table:
  id INTEGER PRIMARY KEY
  file_path TEXT UNIQUE NOT NULL
  filename TEXT NOT NULL
  extension TEXT NOT NULL
  file_size INTEGER
  file_md5 TEXT
  perceptual_hash TEXT
  date_taken DATETIME
  gps_lat REAL
  gps_lon REAL
  city TEXT
  country TEXT
  camera_make TEXT
  camera_model TEXT
  lens TEXT
  iso INTEGER
  aperture REAL
  shutter_speed TEXT
  flash_used BOOLEAN
  orientation INTEGER
  file_created DATETIME
  file_modified DATETIME
  ai_caption TEXT  -- populated later in Phase 2
  ai_tags TEXT     -- populated later in Phase 2 (JSON array)
  ai_scene_type TEXT -- populated later in Phase 2
  ai_quality_score REAL -- populated later in Phase 2
  is_screenshot BOOLEAN DEFAULT FALSE
  is_duplicate_of INTEGER REFERENCES images(id)
  face_count INTEGER DEFAULT 0  -- populated in Phase 2 (face detection)
  organization_status TEXT DEFAULT 'pending'
  scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP
  analyzed_at DATETIME  -- populated in Phase 2

Also create a faces table (populated in Phase 2):
  id INTEGER PRIMARY KEY
  image_id INTEGER REFERENCES images(id)
  embedding BLOB NOT NULL
  bbox_x REAL
  bbox_y REAL
  bbox_w REAL
  bbox_h REAL
  cluster_id INTEGER  -- same person = same cluster_id
  cluster_label TEXT   -- user-assignable name (default: "Person 1", etc.)

Also implement a `status` command:
  photoagent status <path>

  Shows: total images found, images analyzed, breakdown by year/camera/location, disk usage, duplicate count.

Write comprehensive tests for the scanner module.
```

**Agents to deploy:**
- **Agent 1:** Project structure, CLI setup, database schema
- **Agent 2:** EXIF extraction module + reverse geocoding
- **Agent 3:** File hashing (MD5 + perceptual hash)
- **Agent 4:** Tests

**Deliverables:**
- Working `scan` command that catalogs an entire SSD
- Working `status` command
- Test suite with >80% coverage on scanner module

**Estimated time:** 1 Claude Code session (2-4 hours)

---

### Phase 2: Local Vision Analysis Pipeline

**Goal:** Analyze every image locally using AI models. No image data leaves the machine.

**Claude Code Prompt:**

```
Add an `analyze` command to photoagent:
  photoagent analyze <path> [--batch-size 32] [--device auto] [--models clip,caption,quality,faces] [--skip-captions] [--lite]

This command processes all images in the catalog that haven't been analyzed yet.

The --skip-captions flag skips the slow captioning model entirely (recommended on CPU).
The --lite flag runs CLIP tagging + quality assessment only — fastest possible analysis, no captions, no face clustering.

Implement five local analysis modules:

MODULE 1: CLIP Tagger (open_clip_torch)
- Load OpenCLIP ViT-B/32 model
- For each image, compute similarity against a predefined set of ~200 category labels covering:
  - Scene types: beach, mountain, city, restaurant, park, office, home interior, concert, wedding, graduation, birthday, airport, etc.
  - Content: food, animal, pet, car, document, screenshot, meme, selfie, group photo, landscape, sunset, night, etc.
  - Activities: swimming, hiking, dining, cooking, playing, working, traveling, celebrating, etc.
- Store top-10 tags with confidence scores as JSON in ai_tags column
- Also compute and store the CLIP embedding vector using sqlite-vss or chromadb for efficient similarity search later (avoid raw BLOB storage in SQLite — it bloats the DB at ~2KB per image)
- Use batched inference for speed

MODULE 2: Image Captioner (Florence-2-base or LLaVA if GPU available)
- Generate a one-sentence natural language caption for each image
- Store in ai_caption column
- On CPU, DEFAULT to CLIP-based caption construction (don't wait for the user to discover it's slow — make this the default on CPU, with full captioning as opt-in via --models caption):
  Construct caption from top tags: "A [scene_type] photo showing [top objects/activities] in [location if known]"
- Only load the captioning model when explicitly requested on CPU, or auto-enable on GPU
- Unload CLIP model from memory before loading the captioning model to stay under 2GB RAM

MODULE 3: Quality & Type Assessor (Pillow + heuristics)
- Blur detection: compute Laplacian variance — flag images below threshold
- Exposure analysis: check histogram — flag over/underexposed
- Resolution check: flag very small images
- Screenshot detection: check for status bar patterns, exact aspect ratios (phone screens), uniform UI elements
- Store quality score (0-1) in ai_quality_score
- Set is_screenshot flag

MODULE 4: Duplicate Detector
- Use perceptual hashes from Phase 1 to find near-duplicates (hamming distance < 5)
- Use MD5 hashes for exact duplicates
- Set is_duplicate_of to the ID of the earliest (by date_taken) image in each duplicate group
- Store duplicate groups in a separate duplicates table

MODULE 5: Face Detector & Clusterer (insightface / ArcFace)
- Detect faces in each image using insightface's RetinaFace detector
- Extract 512-dim ArcFace embeddings for each detected face
- Store face embeddings in a faces table: (id, image_id, embedding, bbox_x, bbox_y, bbox_w, bbox_h, cluster_id)
- After processing all images, cluster face embeddings using DBSCAN or Chinese Whispers to group the same person across photos
- Assign each cluster a temporary label (Person 1, Person 2, ...) — user can rename later
- This enables the "Group photos of people together" use case from the example
- Skip this module in --lite mode
- Sequential model loading: unload other models before loading insightface to manage memory

Processing requirements:
- Show rich progress bar with ETA
- Support resume — if interrupted, pick up where it left off (check analyzed_at)
- Log all errors but continue processing
- Print summary when done: images analyzed, tags distribution, duplicates found, screenshots detected
- Support --device flag: auto (detect GPU), cpu, cuda, mps (Apple Silicon)
- Warn the user about estimated time based on device and image count before starting

Write tests using sample images.
```

**Agents to deploy:**
- **Agent 1:** CLIP tagger module + label taxonomy
- **Agent 2:** Caption generation module with CPU-default fallback logic
- **Agent 3:** Quality assessment + screenshot detection
- **Agent 4:** Duplicate detection engine
- **Agent 5:** Face detection & clustering module (insightface/ArcFace + DBSCAN)
- **Agent 6:** CLI integration, progress UI, resume logic, --skip-captions/--lite flags
- **Agent 7:** Sequential model loading & memory management (keep < 2GB RAM)
- **Agent 8:** Tests

**Deliverables:**
- Working `analyze` command that processes images 100% locally
- Resumable pipeline with progress tracking
- All images in catalog enriched with tags, captions, quality scores, and face clusters
- --lite and --skip-captions modes for CPU-only users
- Sequential model loading to stay within 2GB RAM budget

**Estimated time:** 2-3 Claude Code sessions (most complex phase)

**Performance expectations:**
- CLIP tagging: ~50-100 images/sec on GPU, ~5-10/sec on CPU
- Captioning: ~2-5 images/sec on GPU, ~0.5-1/sec on CPU (skipped by default on CPU)
- Face detection: ~5-15 images/sec on GPU, ~1-3/sec on CPU
- --lite mode (CLIP + quality only): ~30-60/sec on GPU, ~5-10/sec on CPU
- 10,000 images full pipeline: ~30 min on GPU, ~3-5 hours on CPU
- 10,000 images --lite mode: ~5 min on GPU, ~20-30 min on CPU

---

### Phase 3: Instruction Parser + Organization Planner

**Goal:** Accept natural language instructions, combine with catalog metadata, produce a concrete file reorganization plan. Only text metadata is sent to Claude API.

**Claude Code Prompt:**

```
Add an `organize` command to photoagent:
  photoagent organize <path> "<instruction>" [--dry-run] [--max-preview 50]

This command:
1. Reads the user's natural language instruction
2. Queries the catalog to build a text-only summary of the image library
3. Sends ONLY the text summary + instruction to Claude API (Sonnet)
4. Receives a JSON organization plan
5. Displays the plan for user approval
6. Executes if approved

CRITICAL PRIVACY IMPLEMENTATION:
- Build an intermediate "catalog summary" that contains ONLY text metadata:
  {
    "total_images": 12450,
    "date_range": "2018-01-15 to 2025-03-20",
    "locations": ["Miami, US", "Cancun, MX", "New York, US", ...],
    "tag_distribution": {"beach": 342, "restaurant": 128, "selfie": 890, ...},
    "cameras": ["iPhone 14 Pro", "Canon EOS R5"],
    "yearly_breakdown": {"2023": 3400, "2024": 4100, ...},
    "screenshot_count": 1230,
    "duplicate_groups": 89,
    "quality_issues": {"blurry": 234, "dark": 56},
    "face_clusters": {"Person 1": 342, "Person 2": 210, "Person 3": 89, ...},
    "face_cluster_count": 23
  }
- Also prepare a per-image manifest (text only):
  [
    {"id": 1, "filename": "IMG_3021.jpg", "date": "2023-07-14", "location": "Cancun, MX", "tags": ["beach", "sunset", "landscape"], "caption": "A sunset over a sandy beach with palm trees", "quality": 0.92, "is_screenshot": false, "is_duplicate": false, "faces": ["Person 1", "Person 3"]},
    ...
  ]
- NEVER include file bytes, base64, thumbnails, or any pixel data
- Add an assertion/guard in the API call module that rejects any payload containing base64 or binary patterns

PLAN GENERATION:
Send the catalog summary + instruction to Claude API with a system prompt like:
  "You are a file organization planner. Given a summary of an image library and a user instruction, generate a JSON plan mapping each image ID to its new relative path. Respond ONLY with valid JSON."

The plan format:
  {
    "folder_structure": ["Vacations/2023/Cancun", "Vacations/2023/NYC", "Screenshots/2024", ...],
    "moves": [
      {"id": 1, "from": "DCIM/IMG_3021.jpg", "to": "Vacations/2023/Cancun/beach_sunset_001.jpg"},
      ...
    ],
    "summary": "Organized 12,450 images into 47 folders..."
  }

For large libraries (>5000 images), chunk the per-image manifest and make multiple API calls, then merge plans.

CHUNKING SAFETY: When merging plans from multiple API calls, enforce consistent folder naming across chunks. Send the folder structure from prior chunks as context to subsequent calls to prevent naming conflicts (e.g., "Vacations/2023/Cancun" vs "Travel/Mexico/Cancun"). The final merge step must deduplicate and normalize folder paths.

PLAN DISPLAY:
Use rich tables to show:
- Proposed folder structure (tree view)
- Sample moves (first N, configurable with --max-preview)
- Statistics: how many files move, how many stay, how many renamed
- Estimated time to execute

Ask for confirmation: [approve / reject / modify instruction / export plan as JSON]

Implement --dry-run as default behavior (show plan but don't execute).

Write a privacy audit test that captures all outbound HTTP requests and asserts zero image data is present.
```

**Agents to deploy:**
- **Agent 1:** Catalog summarizer (text-only metadata extraction)
- **Agent 2:** Claude API integration with privacy guards
- **Agent 3:** Plan parser, chunking logic for large libraries
- **Agent 4:** Plan display UI (rich tables, tree view)
- **Agent 5:** Privacy audit tests + integration tests

**Deliverables:**
- Working `organize` command with natural language input
- Privacy-audited API call module
- Beautiful plan preview in terminal

**Estimated time:** 1-2 Claude Code sessions

---

### Phase 4: Execution Engine + Undo System

**Goal:** Safely move/rename files with full undo capability.

**Claude Code Prompt:**

```
Add execution and undo capabilities to photoagent:

EXECUTE (triggered after plan approval in `organize`):
1. Before any moves, create a manifest file at <path>/.photoagent/manifests/<timestamp>.json
   containing every operation with source and destination paths
2. Create all destination directories
3. For each move operation:
   - COPY file to destination first (do NOT move directly)
   - Verify the copy (compare MD5 hashes)
   - Only delete the source after verified copy
   - Update catalog.db with new path
4. Show rich progress bar during execution
5. Handle conflicts: if destination exists, append _001, _002, etc.
6. Handle errors: if any copy fails, log it and continue (don't abort entire operation)
7. Print summary: files moved, files skipped, errors encountered, time taken

UNDO command:
  photoagent undo <path> [--manifest <timestamp>]

1. If no manifest specified, use the most recent one
2. Read the manifest and reverse every operation
3. Same safety: copy back first, verify, then delete
4. Update catalog.db

HISTORY command:
  photoagent history <path>

1. Show all past operations with timestamps, instruction used, files affected
2. Allow selecting any past operation to undo

SAFETY FEATURES:
- Never delete source files until copy is verified
- Never overwrite without conflict resolution
- All operations are logged and reversible
- Support --simulate flag that logs what would happen without touching files
- Detect and handle: read-only files, permission errors, path length limits, special characters in filenames
- Handle cross-volume moves (SSD to SSD, SSD to HDD) correctly using copy+delete

Write thorough tests including edge cases: special characters, long paths, permission errors, interrupted operations.
```

**Agents to deploy:**
- **Agent 1:** File operations engine (copy, verify, delete)
- **Agent 2:** Manifest system + undo logic
- **Agent 3:** Conflict resolution + error handling
- **Agent 4:** History command + CLI integration
- **Agent 5:** Edge case tests

**Deliverables:**
- Safe, reversible file execution
- Complete undo system
- Operation history

**Estimated time:** 1-2 Claude Code sessions

---

### Phase 5: Search, Templates, and Offline Mode

**Goal:** Add power-user features that make the tool indispensable.

**Claude Code Prompt:**

```
Add the following commands to photoagent:

SEARCH command:
  photoagent search <path> "<query>"
  Examples:
    photoagent search /Volumes/MySSD "photos of dogs at the beach"
    photoagent search /Volumes/MySSD "blurry photos from 2023"
    photoagent search /Volumes/MySSD "screenshots containing text about flights"

Implementation:
- Use CLIP embeddings stored in Phase 2 for semantic search
- Encode the query text with CLIP text encoder
- Compute cosine similarity against all stored image embeddings
- Return top results with filename, path, caption, similarity score
- Support filters: --year, --location, --min-quality, --type (photo/screenshot)
- Display results as a rich table

TEMPLATES command (offline organization):
  photoagent organize <path> --template <template_name>

  Built-in templates that require ZERO network access:
  - "by-date": Year/Month/Day folder structure
  - "by-date-location": Year/Month/Location
  - "by-camera": Camera Make/Model
  - "by-type": Photos / Screenshots / Duplicates / Low Quality
  - "cleanup": Move duplicates and low-quality to Review folder
  - "custom": Load from a YAML file defining rules

  Template YAML format:
    name: "My Organization"
    rules:
      - match: {tags_contain: "beach", location_country: "MX"}
        destination: "Mexico Vacations/{year}"
        rename: "{date}_{caption_short}"
      - match: {is_screenshot: true}
        destination: "Screenshots/{year}/{month}"
      - match: {quality_below: 0.3}
        destination: "Review/Low Quality"
      - default:
        destination: "Unsorted/{year}"

EXPORT command:
  photoagent export <path> [--format csv|json] [--output catalog_export.csv]

  Exports the entire enriched catalog (metadata, tags, captions, face clusters, quality scores) as CSV or JSON for interoperability with other tools, spreadsheets, or custom scripts.
  - CSV format: one row per image, JSON arrays flattened into comma-separated strings
  - JSON format: full structured output with nested arrays for tags and faces
  - Supports --filter to export subsets: --filter "year:2023" --filter "tag:beach"

RENAME-PERSON command:
  photoagent rename-person <path> <cluster_id_or_current_label> "<new_name>"

  Renames a face cluster label. After face clustering assigns temporary labels (Person 1, Person 2, ...),
  users can assign real names. This updates the cluster_label in the faces table and is reflected in
  future organize and search operations.

  photoagent list-people <path>
  Shows all face clusters with: label, photo count, and a sample filename for identification.

CONFIG command:
  photoagent config
  Interactive setup for:
  - Default scan extensions
  - Anthropic API key (stored in system keyring, not plaintext)
  - Preferred device (cpu/cuda/mps)
  - Default template

Write tests for semantic search accuracy and template rule matching.
```

**Agents to deploy:**
- **Agent 1:** Semantic search engine using CLIP embeddings (via sqlite-vss/chromadb)
- **Agent 2:** Template system + YAML parser
- **Agent 3:** Export command (CSV/JSON) + filter support
- **Agent 4:** Face cluster management (rename-person, list-people commands)
- **Agent 5:** Config management with secure key storage
- **Agent 6:** Tests

**Deliverables:**
- Natural language photo search
- Offline organization templates
- Catalog export to CSV/JSON
- Face cluster naming and listing
- Secure configuration

**Estimated time:** 1-2 Claude Code sessions

---

### Phase 6: Desktop UI (Optional — Product Launch Phase)

**Goal:** Wrap the CLI in a cross-platform desktop app for non-technical users.

**Claude Code Prompt:**

```
Build a Tauri desktop application wrapping the photoagent CLI:

FEATURES:
- Drag-and-drop folder/drive selection
- Visual grid of scanned photos with AI-generated tags shown on hover
- Natural language instruction input box
- Visual plan preview: show before/after folder tree side by side
- One-click approve/execute/undo
- Progress indicators for scan, analyze, organize operations
- Settings panel for API key, device selection, default templates
- Search bar with instant results shown as image grid

DESIGN:
- Clean, minimal UI — think Apple Photos meets terminal
- Dark mode by default
- Sidebar: drives/folders, operation history
- Main area: image grid or plan preview
- Bottom bar: status, progress, quick actions

TECH:
- Tauri (Rust backend, web frontend)
- Frontend: React + Tailwind
- Backend: calls photoagent Python CLI as subprocess or via PyO3 bindings
- All processing still local — UI is just a wrapper

This is the marketable product layer. The CLI remains the engine.
```

**Agents to deploy:**
- **Agent 1:** Tauri project setup + Rust backend
- **Agent 2:** React frontend — layout, image grid, plan preview
- **Agent 3:** Frontend — instruction input, search, settings
- **Agent 4:** Integration between Tauri and Python backend
- **Agent 5:** Tests + packaging for macOS/Windows/Linux

**Deliverables:**
- Cross-platform desktop app
- Installable packages (.dmg, .exe, .AppImage)

**Estimated time:** 3-5 Claude Code sessions

---

## SSD Access Notes

PhotoAgent accesses the SSD like any other mounted volume:

- **macOS:** `/Volumes/YourSSDName/`
- **Linux:** `/mnt/ssd/` or `/media/username/SSDName/`
- **Windows:** `D:\` or whatever drive letter is assigned

The `scan` command accepts any valid path. No special drivers or permissions needed beyond normal filesystem read/write access. The tool stores its catalog database inside a `.photoagent` hidden folder at the root of the scanned path, so the catalog travels with the drive.

For very large SSDs (1TB+ of images), the tool should:
- Use memory-mapped file reading where possible
- Process in streaming batches, never load all images into RAM
- Support incremental scans so re-runs are fast
- Target < 2GB RAM usage even for 100K+ image libraries
- Use sequential model loading during analysis: unload each model (CLIP → captioner → face detector) before loading the next to stay within memory budget
- Store CLIP embeddings in sqlite-vss or chromadb rather than raw BLOBs to avoid catalog DB bloat (~2KB × image count)

---

## Cost Estimate

| Component | Cost |
|---|---|
| Local vision models | Free (open source) |
| Claude API (text-only planning) | ~$0.001-0.005 per organization run (only text metadata sent) |
| Reverse geocoding | Free (offline database) |
| CLIP / Florence-2 | Free (open source, runs locally) |
| **Total per 10K image library** | **< $0.01 in API costs** |

The privacy-first local approach is not just safer — it's dramatically cheaper than sending images to cloud vision APIs.

---

## Testing Strategy

Each phase includes its own test suite. Additionally:

- **Privacy integration test:** Intercept all HTTP traffic during a full scan → analyze → organize cycle. Assert that zero image bytes are transmitted. Run this in CI.
- **Large library stress test:** Generate 50K dummy images with synthetic EXIF data. Verify scan, analyze, and organize complete without memory issues.
- **Cross-platform test:** Verify on macOS, Linux, Windows (especially path handling).
- **Undo integrity test:** Run organize, then undo, then diff the filesystem against original state. Must be identical.
- **Resume test:** Kill the process mid-analyze. Restart. Verify it picks up where it left off with zero reprocessing.

---

## Claude Code Multi-Agent Strategy

For each phase, open Claude Code and use this pattern:

```
I'm building PhotoAgent Phase [N]. Here's the plan: [paste relevant phase section].

Deploy agents for:
1. [Agent 1 scope]
2. [Agent 2 scope]
3. [Agent 3 scope]

Each agent should work in its own module under src/photoagent/.
Run all tests before considering the phase complete.
```

This ensures parallel development within each phase while maintaining clean module boundaries.

---

## Launch Checklist

- [ ] Phase 1: Scanner works on real SSD with 10K+ images
- [ ] Phase 2: Local analysis completes without network calls
- [ ] Phase 3: Organization plans are accurate and privacy-audited
- [ ] Phase 4: Undo system verified — zero data loss
- [ ] Phase 5: Search returns relevant results, templates work offline
- [ ] Phase 6: Desktop UI installable on macOS and Windows
- [ ] Privacy audit: independent verification that no image data leaves the machine
- [ ] Performance: Full pipeline completes on 10K images in under 1 hour on modern hardware
- [ ] README, LICENSE, and documentation complete
