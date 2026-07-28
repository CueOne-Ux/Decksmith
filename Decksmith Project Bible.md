# DECKSMITH PROJECT BIBLE
## Version 1.0
### CueRated Concepts

---

# Vision

**Decksmith** is a local-first desktop application that bridges the gap between DJ preparation and music production.

It combines library management, intelligent music discovery, AI-assisted creativity, stem separation, mashup creation, extended mix editing and DJ export workflows into one application.

Decksmith is **not** intended to replace Serato, Rekordbox, Traktor, VirtualDJ or Ableton.

Instead, it complements them by eliminating repetitive preparation work and making creative ideas effortless to capture and develop.

---

# Mission

Reduce the time between:

> "That vocal would sound incredible over that beat."

and

> A finished DJ-ready edit.

The software should encourage experimentation without making creative decisions on behalf of the user.

AI assists.

The DJ creates.

---

# Product Philosophy

Decksmith should feel like:

> **Ableton Arrangement View built specifically for DJs.**

It is a creative workstation.

Not another DJ performance application.

---

# Primary Goals

Decksmith should allow a DJ to:

- Organise an entire music library.
- Manage Serato crates.
- Transfer preparation into Rekordbox.
- Discover forgotten music.
- Build mashups quickly.
- Produce extended edits.
- Export polished audio.
- Prepare USBs for performance.

---

# Non-Goals

Decksmith is NOT trying to become:

- Serato
- Rekordbox
- Ableton Live
- VirtualDJ
- Traktor

The application is intentionally focused on preparation and creation.

---

# Target User

Initially:

Cue.

Eventually:

Professional DJs.

Open-format DJs.

Wedding DJs.

Club DJs.

Festival DJs.

Content creators.

Radio presenters.

---

# Platform

Desktop only.

Windows

macOS

Offline-first.

No mandatory cloud.

---

# Technology

Desktop

Tauri

Frontend

React + TypeScript

Backend

Python

Database

SQLite

Audio

FFmpeg

Stem Separation

Demucs

Analysis

Essentia

Metadata

Mutagen

Testing

Pytest

Playwright

---

# Core Modules

1. Library

2. Transfer

3. Arrangement

4. Stems

5. Master

6. Export

7. AI Assistant

---

# MODULE 1 — Library

The Library is the heart of Decksmith.

Everything else depends on it.

## Features

- Scan local music folders
- Locate Serato libraries automatically
- Read crates
- Read subcrates
- Import Rekordbox playlists (future)
- Search
- Smart filters
- Genre
- Mood
- Energy
- BPM
- Musical key
- Ratings
- Colour tags
- Comments
- Year
- Artwork
- Duplicate detection
- Missing files
- Broken paths
- Recently added
- Recently modified
- Recently played
- Preview player
- Waveform preview
- Smart playlists
- Bulk editing

---

# MODULE 2 — Transfer

Purpose:

Synchronise preparation work.

## Workflow

Read Serato

↓

Compare previous sync

↓

Identify changed crates

↓

Transfer compatible metadata

↓

Generate Rekordbox import

↓

Validation report

↓

Launch Rekordbox

## Preserve whenever technically possible

- Playlist hierarchy
- Track order
- BPM
- Key
- Cue points
- Saved loops
- Comments
- Ratings

Never overwrite without confirmation.

Never silently discard metadata.

---

# MODULE 3 — Arrangement

The flagship feature.

A four-channel offline mashup workstation.

## Layout

Four primary channels.

Each channel accepts:

- complete songs
- audio clips
- rendered edits
- stem groups

Each song expands into:

- Vocals
- Drums
- Bass
- Other

Collapse hides stems.

Expand reveals editable lanes.

## Clip Editing

- Move
- Split
- Trim
- Duplicate
- Loop
- Reverse
- Fade
- Crossfade
- Snap to beat
- Quantise
- Gain
- Pan
- Pitch
- Tempo
- Colour
- Group
- Lock

## Playback

- Accurate preview
- Loop playback
- Selection playback
- Timeline zoom
- Marker navigation

No scratching.

No controller support.

No live performance engine.

---

# MODULE 4 — Stem Engine

Integrated into Arrangement.

Never separate application.

Workflow

Import track

↓

Separate Stems

↓

Background processing

↓

Cache

↓

Reveal stem lanes

↓

Edit

↓

Render

Operations

- Solo
- Mute
- Gain
- Drag
- Duplicate
- Bounce
- Freeze
- Regenerate

All processing remains local.

---

# MODULE 5 — Master

Per Track

- Gain
- Pan
- 3-band EQ
- High-pass
- Low-pass
- Compressor

Master Bus

- EQ
- Stereo width
- Limiter
- Peak meter
- LUFS meter
- Clipping detection

---

# MODULE 6 — Export

Audio

- WAV
- AIFF
- MP3
- Stems
- Project archive

DJ

- Rekordbox transfer package
- USB readiness report
- Playlist validation

---

# MODULE 7 — AI Assistant

The AI is an assistant.

Never an autopilot.

---

## The Forge

The home screen.

A place where ideas begin.

Users drag songs into The Forge.

Decksmith automatically:

- analyses BPM
- analyses key
- estimates compatibility
- queues stem separation
- suggests pitch changes
- suggests tempo
- suggests intro/outro regions
- builds a draft project

---

## Mashup Drafts

Every idea becomes a saved draft.

Status examples

Idea

Analysing

Stems Processing

Ready

Needs Review

Finished

Nothing is lost.

---

## Compatibility Engine

Every song pairing receives a compatibility score based on:

- BPM proximity
- Harmonic compatibility
- Phrase alignment
- Intro/outro overlap
- Energy curve
- Groove similarity
- Vocal density
- Instrumentation balance

The score explains *why* it was calculated.

---

## Intelligent Crates

Natural-language search across the local library.

Examples

"Deep Afro with female vocals."

"Peak-time amapiano."

"Warm sunset opener."

Results come only from the user's own collection.

---

## Memory Triggers

Surface forgotten music.

Examples

"You haven't played this track in 3 years."

"You tagged this as 'sunset'."

"You previously mixed this after Track X."

"This matches five tracks you recently added."

---

## Rabbit Hole

Creative exploration.

Choose one track.

Decksmith explores related music based on:

- groove
- percussion
- harmonic profile
- energy
- instrumentation
- previous projects
- personal history

The goal is inspiration, not automation.

---

## AI Set Builder

Inputs

- Venue
- Genre
- Duration
- Energy curve
- Audience
- Must-play tracks
- Avoid tags

Outputs

A proposed running order using **only tracks in the user's library**.

The user remains in control.

---

## Smart Render

Before exporting:

Decksmith checks for:

- clipping
- abrupt transitions
- vocal collisions
- bass masking
- phrase endings
- silence
- inconsistent loudness

Warnings explain the issue instead of silently fixing it.

---

# Background Workers

Long-running jobs must never block the interface.

Workers include

- Stem separation
- Audio analysis
- Waveform generation
- Rendering
- Library scanning
- Duplicate detection
- Artwork extraction

Each worker reports:

Queued

Running

Completed

Failed

Cancelled

---

# Database

Core tables

Tracks

Artists

Albums

Playlists

Crates

Projects

Timeline Clips

Stem Cache

Cue Points

Loops

Beatgrids

Transfer History

Exports

Render Queue

User Tags

AI Drafts

AI Suggestions

Project History

---

# File Safety

Never modify:

Original music

Serato database

Rekordbox database

Every render creates new files.

Every destructive operation requires confirmation.

Automatic backups before writing.

---

# Cache

Cache

Waveforms

Stems

Artwork

Analysis

Spectrograms

Deleting cache must never delete projects.

---

# Projects

Projects store:

Timeline

Markers

Sections

Clip positions

Tempo

Pitch

Automation

Master settings

Links to original files

Projects should reference media rather than duplicate it whenever possible.

---

# Interface

## Experience Principles

- Dark, focused and professional.
- High contrast without harsh glare.
- Dense enough for serious audio work, but never visually noisy.
- Information hierarchy must remain clear at a glance.
- Editing controls appear in context instead of permanently crowding the workspace.
- The arrangement and its waveforms are always the visual priority.
- Colour communicates track identity, stem type, state and warnings; it is never decorative noise.

## Visual Direction

The interface should combine the restraint of a modern productivity tool with the precision of a professional audio workstation.

The supplied visual references establish the following direction:

- Near-black and charcoal layered surfaces rather than a single flat black background.
- Fine borders, subtle elevation and restrained shadows to separate panels.
- Softly rounded panels and clips, balanced by a strict timeline grid.
- Purple as the primary brand and selection accent.
- Track and stem colours may extend into blue, cyan, magenta, orange and red.
- Bright gradients are reserved for high-value moments such as a selected clip, compatibility result, active render or primary action.
- Crisp, modern sans-serif typography with compact labels and comfortable spacing.
- Thin line icons with filled or illuminated states for active tools.
- Waveforms should be detailed, legible and visually dominant.
- Animation should communicate state changes, processing and navigation—not decorate idle screens.

## Workspace Structure

Decksmith uses a persistent three-panel workflow:

### Left — Library

- Navigation
- Crates and playlists
- Search and filters
- Track browser
- Project and draft access

The panel may collapse to an icon rail when more timeline space is needed.

### Centre — Arrangement

- Timeline ruler and beat grid
- Markers and section labels
- Four primary song channels
- Expandable stem lanes
- Coloured waveform clips
- Playhead, selections and loop regions

The arrangement should feel spacious and horizontally oriented. Clips must remain easy to distinguish at every useful zoom level.

### Right — Inspector

- Context-sensitive clip properties
- Gain, pan, tempo and pitch
- Fade and crossfade controls
- EQ, filters and compression
- Compatibility explanations
- Export warnings

The inspector changes with the current selection and may collapse completely.

### Bottom — Transport and Status

- Playback and navigation
- Current time and musical position
- Tempo and key context
- Zoom controls
- Background job progress
- Warnings and system status

## Arrangement Behaviour

- A complete song appears as one compact waveform lane by default.
- Expanding a song reveals Vocals, Drums, Bass and Other directly below it.
- Stem lanes inherit a related colour family while remaining individually identifiable.
- Selected clips use a stronger outline, brighter waveform or restrained glow.
- The playhead must remain visible across all channels.
- Muted, locked, frozen and processing states must be distinguishable without relying on colour alone.
- Hover and selection reveal editing handles only when useful.
- Context menus provide fast editing without replacing visible primary controls.

## Colour Roles

- **Canvas:** near-black.
- **Panels:** layered charcoal and deep blue-black.
- **Primary text:** warm white.
- **Secondary text:** cool grey.
- **Brand and selection:** electric purple.
- **Waveforms:** track-assigned colours with accessible contrast.
- **Success:** green.
- **Warning:** amber.
- **Error or clipping:** red.
- **Disabled or unavailable:** desaturated grey.

Exact colour tokens should be defined during implementation and tested for accessibility.

## Avoid

- Skeuomorphic DJ decks or turntables.
- A neon-heavy gaming aesthetic.
- Excessive gradients, glow or glass effects.
- Oversized dashboard cards that reduce working space.
- Tiny controls that prioritise density over accuracy.
- Permanent toolbars for actions that belong in context.
- Visual similarity to a live-performance application.
- Decorative AI imagery or effects that make AI feel like the product rather than an assistant.

---

# Development Milestones

## Phase 1

Library

## Phase 2

Transfer

## Phase 3

Arrangement

## Phase 4

Stem Engine

## Phase 5

Master

## Phase 6

Export

## Phase 7

AI Assistant

No phase begins until the previous one passes testing.

---

# Acceptance Criteria

**MVP status (macOS, Apple Silicon): complete and packaged.** The signed local application includes its analysis service, offline HTDemucs stem engine, cache lifecycle and Phase 7 Forge assistant. Windows packaging remains a platform release task, not an outstanding product feature.

Decksmith MVP is complete when it can:

✓ Scan a Serato library.

✓ Detect modified crates.

✓ Transfer playlists into Rekordbox.

✓ Import four songs.

✓ Analyse BPM and key.

✓ Generate waveforms.

✓ Separate stems locally.

✓ Cache stems.

✓ Display expandable stem lanes.

✓ Move stems freely between four arrangement channels.

✓ Preview playback accurately.

✓ Render WAV.

✓ Render MP3.

✓ Save and reopen projects.

✓ Export a Rekordbox-ready transfer package.

✓ Generate AI-assisted mashup drafts.

✓ Suggest compatible songs from the user's library.

✓ Build AI-assisted draft setlists using only local music.

---

# Guiding Principle

Decksmith should never replace the DJ.

It should remove repetitive work, surface forgotten ideas, organise creativity and make experimentation almost effortless.

Every feature should answer one question:

> **Does this help the DJ create something they were unlikely to create without it?**

If the answer is yes, it belongs in Decksmith.

If the answer is merely "it looks clever", it does not.

---

# Product Tagline

**Decksmith**

**From Crates to Creations.**

---

# Long-Term Roadmap (Beyond MVP)

## Version 2

- Multi-library support (Traktor, VirtualDJ, Engine DJ)
- Flexible beatgrid editing
- Batch cue and loop tools
- Project templates

## Version 3

- Collaborative project sharing
- Cloud backup (optional)
- AI-assisted transition suggestions
- Live preview enhancements

## Version 4

- Video timeline
- Lighting cue export
- Performance analytics
- Plugin architecture for future extensions

The roadmap should never compromise the core philosophy: keep the DJ in control, automate the repetitive work, and make creativity easier to capture.
