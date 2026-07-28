# Decksmith

Decksmith is a local-first desktop workstation for DJ library preparation, music discovery and edit creation.

## Current phase

The macOS MVP is complete and packaged as a signed, local-first desktop application. The four-channel Arrangement provides sample-accurate playback, editable and isolatable stems, directional key and tempo matching, persistent clip/master processing, EBU R128 validation, Smart Render warnings and local WAV/MP3 mixdown. Forge adds explainable compatibility matching, mashup drafts and local-library setlist drafts. Transfer remains accepted against the local Serato library and Rekordbox 6.8.5 XML bridge.

The current frontend slice includes:

- A desktop application shell
- Library and crate navigation
- Search across track metadata
- List and artwork-grid views
- Contextual track inspector
- Preview transport
- Filter controls
- Audio file selection and queued-analysis feedback
- Empty and selected states
- Real local audio preview, seeking and track navigation
- Sortable track columns and persistent filters
- Persistent ratings, user tags and colour labels
- Music-folder management and safe rescanning
- Missing-file and metadata-error reporting
- SHA-256 confirmed duplicate detection
- Live background jobs with safe cancellation
- Automatic, read-only Serato discovery with crate hierarchy and track order
- 4096-pixel FFmpeg waveform generation with an app-owned cache
- Headless FFmpeg and NumPy BPM, Camelot key and signal-energy analysis with no audio-device dependency
- Persistent analysis jobs with progress, cancellation, retry and per-track errors
- Embedded year and comment display in the track inspector
- Embedded artwork extraction with an app-owned cache
- Multi-select rating, colour and tag editing
- Persistent rule-based smart playlists
- Recently played timestamps and preview counts
- Mood metadata and energy filtering
- Dedicated recently added, modified and played views
- Safe local comment editing that never modifies audio files

The native shell loads the indexed SQLite library. Sample tracks are used only by the browser-only design preview before a native library has been indexed.

The current Transfer slice includes:

- Durable read-only Serato snapshots
- Comparison against the previous snapshot
- Added, modified, reordered, unchanged and removed crate detection
- Track-level added and removed counts
- Explicit unmatched, missing and duplicate-name warnings
- Metadata coverage for BPM, key, comments and ratings
- Read-only Serato Markers2 cue extraction for MP3 files
- Direct, read-only metadata and Serato marker extraction for crate tracks that are not already indexed in Decksmith
- Cloud-only placeholder detection that preserves playlist locations without forcing downloads
- Cue names, positions and Hot Cue A-C slot preservation
- Explicit Hot Cue D-H conversion to named memory cues under the published XML contract
- Fixture-validated Serato saved-loop extraction and Rekordbox memory-loop export
- Selectable crate transfer plans
- Rekordbox XML 1.0.0 generation
- Playlist hierarchy and track order preservation
- Compatible BPM, key, comment, rating, colour and file metadata export
- Atomic export packages with XML, instructions, a JSON validation report and a hash manifest
- SHA-256 integrity value for the generated XML
- Structural XML validation before a package can be recorded as completed
- Recorded-package verification and tamper detection before handoff
- Safe Finder reveal and user-triggered Rekordbox launch actions
- Persistent transfer history
- A dedicated native Transfer workspace

Transfer packages are always created in a new Decksmith-owned folder. Decksmith does not write to the Serato database, the Rekordbox database or source audio files.

The current Arrangement slice includes:

- Persistent arrangement projects with tempo and four primary channels
- Source-linked timeline clips that reference original library files without copying or modifying them
- Automatic full project history snapshots before project and clip writes
- Adding complete library tracks to any channel
- Dragging clips between channels with project-tempo beat snap and selectable beat divisions
- Dragging source-library tracks directly onto a chosen channel and timeline position
- One-action quantise for aligning a selected clip to the active beat grid
- Non-destructive playhead split, source trim and duplicate operations
- Draggable clip-start and clip-end handles for snap-aware trim or source-bounded extension, with Option-drag free movement and reverse-safe source mapping
- Exact target-BPM entry, one-click project-tempo matching, and Final Cut-style Shift-drag end retiming that preserves the selected source span
- Directional key matching between any two keyed clips, with Camelot and standard-key parsing plus relative-key handling when major/minor modes differ
- Persistent whole-clip loop, reverse, fade-in and fade-out settings
- Overlap-aware crossfades that apply matching outgoing and incoming fade curves
- Persistent editable markers and timed sections with colour labels and timeline navigation
- Clickable timeline ruler, lane playhead placement and cue-aware project duration
- Maximum-height channel lanes by default and pointer-anchored trackpad zoom from 0.6 to 48 pixels per second
- Timeline shortcuts for preview, split, marker or section creation and cue navigation
- Persistent In/Out selection regions with selected-clip loop audition
- Full project undo and redo that restores project settings, clips, fades, markers and sections
- Command-click multi-selection with persistent clip groups and linked timeline movement
- Persistent per-clip three-band EQ, high-pass, low-pass and compression controls
- Persistent master three-band EQ, stereo width, gain and limiter controls
- Persistent project LUFS targets with measured master-gain recommendations
- One-save batch gain, colour, mute and lock edits across selected clips
- Whole-group channel shifting with locked-clip and channel-boundary protection
- Overlap-aware estimated peak and master-headroom warnings
- Persistent project key context and live master plus per-channel preview metering
- Undoable multi-clip deletion with locked-clip protection and Delete/Backspace shortcuts
- Sample-accurate four-channel audition from one shared output clock, with automatic local PCM preparation and output-latency-aware playhead timing
- BPM-, time-signature- and snap-derived beat grids that remain phase-locked at every zoom level
- Audition handling for mute, solo, clip fades, clip/master processing and persistent selection loops
- Real Demucs separation progress plus individual local audition controls for completed vocals, drums, bass and other stems
- Full-song or isolated-stem source switching on an existing clip without changing its timing or edit settings
- Persistent per-lane Mute and Solo for the four-stem mixer: mute Vocals for an instrumental, solo Vocals for an acapella, or combine any set of stems
- Automatic stem-mix preparation shared by arrangement playback, prepared waveforms, Smart Render and WAV/MP3 export—no manual preview render required after a stem change
- Adding Vocals, Drums, Bass or Other as independent timeline clips on any arrangement channel
- Dragging any ready expanded stem lane directly onto an exact channel and timeline position
- Independent stem-clip move, trim, split, duplicate, loop, reverse, fade, gain, pan, pitch, tempo, mute, solo, lock and grouping operations
- Persistent source freeze/unfreeze with the original source settings preserved in undo/redo history
- Stable bounced PCM copies placed after the source clip, ready to move and edit without altering the original audio
- Combined live level feedback with the number of currently sounding clips
- Pan-aware Web Audio routing, per-clip processing, master tone/width/limiting and independent channel analysers during simultaneous audition
- Uninterrupted clip selection and real-time clip/master gain, pan, EQ, filter, dynamics, mute and solo adjustment during arrangement playback
- Gain- and tone-responsive timeline waveforms, maximum-height channel lanes by default and first-gesture trackpad zoom without button activation
- FFmpeg-backed, 44.1 kHz stereo preview rendering for reverse, independent pitch and tempo processing
- Persistent queued, running, completed, failed and cancelled clip-render jobs with progress, retry, regeneration and batch rendering
- Signature-validated processed-clip caching with atomic publication, stale detection and source-file change checks
- Tempo-aware source mapping across trim, split, resize, waveform display and playback
- Undoable single- or multi-clip trim-to-selection with source mapping preserved
- Persistent clip placement, gain, pan, pitch, tempo, mute, solo, lock and colour settings
- Expandable Vocals, Drums, Bass and Other stem lanes in the project model
- A source library, central timeline, contextual clip inspector and bottom preview transport
- Source-derived mirrored waveforms mapped precisely through trim, split, reverse and zoom states
- Project save, reopen and list support through the native shell
- Explicit stem-lane mix states backed by the persistent project, history, render and cache models

The current Stem Engine foundation includes:

- A dedicated Python 3.11 stem runtime, isolated from Decksmith's lightweight application backend
- Explicit local Demucs capability and version detection without crashing the Arrangement workspace when the optional engine is absent
- Persistent queued, running, completed, failed and cancelled stem-job states
- App-owned stem cache records tied to the exact source-file modification state and separation model
- Four-stem validation for Vocals, Drums, Bass and Other before any result is published
- Cache-only temporary processing, atomic result promotion and cleanup of partial or cancelled work
- Source-change detection before and after separation, with no write access to original music
- Cache reuse, retry, cancellation and explicit regeneration controls in the clip inspector
- Expandable stem lanes that distinguish ready, processing and not-separated track states
- Native progress events that keep long-running separation work off the interface thread
- Source-safe stem clips that use the exact cached WAV as their rendering and waveform source

The current Forge slice includes:

- Explainable local compatibility matching based on BPM, key, energy, genre and analysis confidence
- Persistent two-song mashup drafts with one-click arrangement creation
- Directional anchor/partner selection so the DJ controls which song leads the idea
- Local-library draft setlists with duration, genre, energy-curve, must-play and avoid-tag controls
- Persistent saved drafts that never upload music or metadata
- Deterministic offline suggestions that remain usable without an account or internet connection

The current audio export slice includes:

- User-selected WAV and MP3 mixdown destinations
- Atomic output publication that never writes to source audio
- 24-bit, 44.1 kHz stereo WAV and high-quality MP3 output
- Timeline placement, clip gain, pan, fades, mute/solo state, three-band EQ, filters, compression, master EQ, stereo width, master gain and limiter processing
- Exact prepared song or isolated-stem sources, including tempo, pitch, trim and reverse edits
- Export lockout until every audible clip has current prepared audio
- EBU R128 integrated-LUFS, loudness-range and true-peak measurement of the actual processed mix
- Real rendered-signal silence detection with clickable timeline locations
- Smart Render checks for true-peak clipping, low headroom, loudness-target variance, vocal collisions, bass masking and abrupt transitions
- One-click master-gain adjustment toward the selected loudness target, followed by an explicit re-analysis
- Persistent Smart Render reports tied to a SHA-256 project/render signature and automatically invalidated by audio-affecting edits
- Persistent per-project audio export history with format, mode, destination, file size, SHA-256 digest and missing-file state
- Optional two-pass EBU R128 loudness-targeted WAV/MP3 derivatives that leave the project master and original-level exports unchanged
- Post-normalisation LUFS and true-peak verification before a targeted derivative is published

The acceptance package was generated from a real Serato snapshot with 34 tracks, 20 cues and 3 saved loops. It passed Decksmith's XML and SHA-256 manifest checks and rendered as a populated playlist in Rekordbox 6.8.5. Validation stopped at Rekordbox's read-only XML bridge; no track was dragged into Collection and no Rekordbox database was modified.

## Library scanner

The Python core scans folders read-only, persists discovered tracks in SQLite, skips unchanged files and marks removed files as missing without deleting their records.

Run the tests:

```bash
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
```

Run a manual scan:

```bash
PYTHONPATH=backend .venv/bin/python -m decksmith.cli \
  --database ./decksmith-dev.db \
  scan "/path/to/music"
```

Install the isolated Python dependencies used for metadata and audio analysis:

```bash
.venv/bin/pip install -r backend/requirements.txt
```

Install the optional local stem engine in its own environment:

```bash
/Users/djcue1/.local/bin/python3.11 -m venv .venv-stems
.venv-stems/bin/python -m pip install --no-cache-dir -r backend/requirements-stems.txt
```

Decksmith discovers `.venv-stems` automatically during development. The macOS release contains its own isolated Demucs executable and HTDemucs model, so stem separation remains local and does not depend on the project folder or an internet connection.

## Run locally

```bash
npm install
npm run dev
```

The local preview opens at `http://127.0.0.1:1420`.

Run the native desktop application:

```bash
npm run desktop
```

## Production build

```bash
.venv/bin/pip install -r backend/requirements-build.txt
.venv-stems/bin/pip install -r backend/requirements-build.txt
npm run desktop:build
```

The signed application is copied to `release/Decksmith.app`. The complete app is about 647 MB on Apple Silicon, including the local analysis service, stem engine and offline model. Compiler output is not part of the app and can be removed after packaging with `npm run desktop:clean`.

## Transfer commands

Create a read-only snapshot and compare it with the previous one:

```bash
PYTHONPATH=backend .venv/bin/python -m decksmith.cli \
  --database ./decksmith-dev.db \
  transfer-snapshot
```

Create a Rekordbox XML package after reviewing the plan:

```bash
PYTHONPATH=backend .venv/bin/python -m decksmith.cli \
  --database ./decksmith-dev.db \
  transfer-export "/path/to/export/folder" \
  --crate-id 1
```

## Release status

- macOS Apple Silicon application: built, ad-hoc signed and verified
- Bundled local service: verified independently of the development environment
- Bundled Demucs engine: verified with a real four-stem separation
- Application database: schema 25, with existing libraries migrated in place
- Cache lifecycle: unreferenced renders, stems and consolidated audio are pruned without touching source music or projects
- Consolidated audio: bounced or frozen sources can be revealed in Finder for handoff or copying
- Windows packaging: the runtime recipe is source-complete but must be built and signed on Windows; it is not represented as validated by this macOS build
