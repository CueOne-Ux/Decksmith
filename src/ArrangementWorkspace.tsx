import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { save } from "@tauri-apps/plugin-dialog";
import {
  ArrowCounterClockwise,
  ArrowClockwise,
  ArrowsLeftRight,
  ArrowsOutLineHorizontal,
  CaretDown,
  CaretLeft,
  CaretRight,
  Copy,
  DownloadSimple,
  FolderOpen,
  FloppyDisk,
  Flag,
  Magnet,
  MapPin,
  Lock,
  LockOpen,
  MagnifyingGlass,
  Minus,
  MusicNotes,
  Pause,
  Play,
  Plus,
  Repeat,
  Scissors,
  SlidersHorizontal,
  SpeakerHigh,
  SpeakerSlash,
  Trash,
  Waveform,
} from "@phosphor-icons/react";

export type ArrangementLibraryTrack = {
  id: number;
  title: string;
  artist: string;
  bpm: number;
  key: string;
  duration: string;
  color: string;
  path?: string;
  missing?: boolean;
};

type ProjectSummary = {
  id: number;
  name: string;
  tempo: number;
  clip_count: number;
  duration_seconds: number;
  updated_at: string;
};

type ArrangementProject = {
  id: number;
  name: string;
  tempo: number;
  musical_key: string;
  time_signature_numerator: number;
  time_signature_denominator: number;
  snap_enabled: number;
  snap_beats: number;
  selection_start_seconds: number | null;
  selection_end_seconds: number | null;
  selection_loop_enabled: number;
  master_gain_db: number;
  master_limiter_enabled: number;
  master_low_eq_db: number;
  master_mid_eq_db: number;
  master_high_eq_db: number;
  master_stereo_width: number;
  target_lufs: number;
  updated_at: string;
};

type ProjectMarker = {
  id: number;
  project_id: number;
  marker_kind: "marker" | "section";
  name: string;
  start_seconds: number;
  end_seconds: number | null;
  color: string;
};

type ArrangementClip = {
  id: number;
  project_id: number;
  track_id: number;
  clip_kind: "song" | StemKind | "rendered";
  title: string;
  artist: string;
  path: string;
  source_bpm: number | null;
  source_key: string;
  source_duration_seconds: number;
  channel: number;
  start_seconds: number;
  source_in_seconds: number;
  duration_seconds: number;
  gain_db: number;
  pan: number;
  pitch_semitones: number;
  tempo_percent: number;
  color: string;
  expanded: number;
  locked: number;
  muted: number;
  solo: number;
  loop_enabled: number;
  reversed: number;
  fade_in_seconds: number;
  fade_out_seconds: number;
  eq_low_db: number;
  eq_mid_db: number;
  eq_high_db: number;
  highpass_hz: number;
  lowpass_hz: number;
  compressor_enabled: number;
  compressor_threshold_db: number;
  compressor_ratio: number;
  group_id: number | null;
  rendered_mode?: "freeze" | "bounce" | null;
  stem_states: Partial<Record<StemKind, StemLaneState>>;
};

type ArrangementPayload = {
  project: ArrangementProject;
  clips: ArrangementClip[];
  markers: ProjectMarker[];
  selected_clip_id?: number;
  selected_marker_id?: number;
  selected_clip_ids?: number[];
  can_undo: boolean;
  can_redo: boolean;
};

type StemKind = "vocals" | "drums" | "bass" | "other";

type StemLaneState = {
  muted: number;
  solo: number;
};

type StemAsset = {
  track_id: number;
  stem_kind: StemKind;
  model: string;
  source_modified_ns: number;
  path: string;
  file_size: number;
};

type StemJob = {
  id: number;
  track_id: number;
  model: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  phase: string;
  progress: number;
  stale: number;
  error: string | null;
};

type StemStatusPayload = {
  capability: {
    available: boolean;
    engine: string;
    version: string;
    default_model: string;
    message: string;
  };
  model: string;
  jobs: StemJob[];
  stems: StemAsset[];
  ready_track_ids: number[];
};

type StemProgressEvent = {
  event: "progress" | "complete";
  data: {
    track_id: number;
    status: StemJob["status"];
    phase: string;
    progress: number;
    stem_count: number;
    cached: boolean;
    error: string;
  };
};

type RenderAsset = {
  clip_id: number;
  signature: string;
  source_modified_ns: number;
  path: string;
  file_size: number;
  duration_seconds: number;
  waveform_path: string;
};

type RenderJob = {
  id: number;
  clip_id: number;
  signature: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  phase: string;
  progress: number;
  stale: number;
  error: string | null;
};

type RenderStatusPayload = {
  capability: {
    available: boolean;
    engine: string;
    version: string;
    message: string;
  };
  jobs: RenderJob[];
  renders: RenderAsset[];
  ready_clip_ids: number[];
};

type RenderProgressEvent = {
  event: "progress" | "complete";
  data: {
    clip_id: number;
    status: RenderJob["status"];
    phase: string;
    progress: number;
    cached: boolean;
    path: string;
    error: string;
  };
};

type AudioExportResult = {
  id: number;
  project_id: number;
  format: "wav" | "mp3";
  path: string;
  file_size: number;
  duration_seconds: number;
  clip_count: number;
  sample_rate: number;
  export_mode: "original" | "loudness_targeted";
  target_lufs: number | null;
  destination_path: string;
  sha256: string;
  integrated_lufs: number | null;
  true_peak_dbfs: number | null;
  created_at: string;
  exists: boolean;
};

type SmartRenderIssue = {
  severity: "error" | "warning" | "info";
  code: string;
  title: string;
  detail: string;
  start_seconds: number | null;
  end_seconds: number | null;
  clip_ids: number[];
};

type SmartRenderReport = {
  audit_id: number;
  project_id: number;
  status: "ready" | "warning" | "blocked";
  analyzed_at: string;
  duration_seconds: number;
  clip_count: number;
  metrics: {
    integrated_lufs: number | null;
    true_peak_dbfs: number | null;
    loudness_range_lu: number | null;
    threshold_lufs: number | null;
    target_lufs: number;
    gain_to_target_db: number | null;
    recommended_master_gain_db: number | null;
    normalization_offset_db: number | null;
  };
  silence_intervals: Array<{ start_seconds: number; end_seconds: number; duration_seconds: number }>;
  issues: SmartRenderIssue[];
  counts: { error: number; warning: number; info: number };
  project_signature: string;
  fresh: boolean;
  created_at?: string;
};

type ArrangementWorkspaceProps = {
  tracks: ArrangementLibraryTrack[];
};

type ClipResizeEdge = "start" | "end";

type ScheduledAudioVoice = {
  clipId: number;
  source: AudioBufferSourceNode;
  gain: GainNode;
  envelope: GainNode;
  panner: StereoPannerNode;
  lowEq: BiquadFilterNode;
  midEq: BiquadFilterNode;
  highEq: BiquadFilterNode;
  highpass: BiquadFilterNode;
  lowpass: BiquadFilterNode;
  compressor: DynamicsCompressorNode;
};

type ScheduledMasterControls = {
  gain: GainNode;
  lowEq: BiquadFilterNode;
  midEq: BiquadFilterNode;
  highEq: BiquadFilterNode;
  leftToSide: GainNode;
  rightToSide: GainNode;
  limiter: DynamicsCompressorNode;
};

type OutputClockAudioContext = AudioContext & {
  outputLatency?: number;
  getOutputTimestamp?: () => { contextTime: number; performanceTime: number };
};

const channelColors = ["violet", "cyan", "rose", "amber"];
const minimumTimelineZoom = 0.6;
const maximumTimelineZoom = 48;
const liveClipControlKeys = new Set([
  "gain_db", "pan", "muted", "solo", "eq_low_db", "eq_mid_db", "eq_high_db",
  "highpass_hz", "lowpass_hz", "compressor_enabled", "compressor_threshold_db",
  "compressor_ratio", "fade_in_seconds", "fade_out_seconds",
]);

type AudioChain = {
  input: AudioNode;
  output: AudioNode;
  nodes: AudioNode[];
};

type ThreeBandEqChain = AudioChain & {
  low: BiquadFilterNode;
  mid: BiquadFilterNode;
  high: BiquadFilterNode;
};

type StereoWidthChain = AudioChain & {
  leftToSide: GainNode;
  rightToSide: GainNode;
};

function createThreeBandEq(
  context: AudioContext,
  lowDb: number,
  midDb: number,
  highDb: number,
): ThreeBandEqChain {
  const low = context.createBiquadFilter();
  low.type = "lowshelf";
  low.frequency.value = 120;
  low.gain.value = lowDb;
  const mid = context.createBiquadFilter();
  mid.type = "peaking";
  mid.frequency.value = 1000;
  mid.Q.value = 1;
  mid.gain.value = midDb;
  const high = context.createBiquadFilter();
  high.type = "highshelf";
  high.frequency.value = 8000;
  high.gain.value = highDb;
  low.connect(mid);
  mid.connect(high);
  return { input: low, output: high, nodes: [low, mid, high], low, mid, high };
}

function createStereoWidth(context: AudioContext, width: number): StereoWidthChain {
  const input = context.createGain();
  const splitter = context.createChannelSplitter(2);
  const mid = context.createGain();
  const side = context.createGain();
  const leftToMid = context.createGain();
  const rightToMid = context.createGain();
  const leftToSide = context.createGain();
  const rightToSide = context.createGain();
  const midToLeft = context.createGain();
  const midToRight = context.createGain();
  const sideToLeft = context.createGain();
  const sideToRight = context.createGain();
  const merger = context.createChannelMerger(2);
  leftToMid.gain.value = 0.5;
  rightToMid.gain.value = 0.5;
  leftToSide.gain.value = 0.5 * width;
  rightToSide.gain.value = -0.5 * width;
  sideToRight.gain.value = -1;
  input.connect(splitter);
  splitter.connect(leftToMid, 0);
  splitter.connect(rightToMid, 1);
  splitter.connect(leftToSide, 0);
  splitter.connect(rightToSide, 1);
  leftToMid.connect(mid);
  rightToMid.connect(mid);
  leftToSide.connect(side);
  rightToSide.connect(side);
  mid.connect(midToLeft);
  mid.connect(midToRight);
  side.connect(sideToLeft);
  side.connect(sideToRight);
  midToLeft.connect(merger, 0, 0);
  sideToLeft.connect(merger, 0, 0);
  midToRight.connect(merger, 0, 1);
  sideToRight.connect(merger, 0, 1);
  return {
    input,
    output: merger,
    nodes: [
      input, splitter, mid, side, leftToMid, rightToMid, leftToSide, rightToSide,
      midToLeft, midToRight, sideToLeft, sideToRight, merger,
    ],
    leftToSide,
    rightToSide,
  };
}

function analyserLevelDb(analyser: AnalyserNode | null) {
  if (!analyser) return -60;
  const samples = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(samples);
  let energy = 0;
  for (const sample of samples) energy += sample * sample;
  const rms = Math.sqrt(energy / samples.length);
  return rms <= 0.000001 ? -60 : Math.max(-60, 20 * Math.log10(rms));
}

const stemDefinitions: Array<{ kind: StemKind; label: string }> = [
  { kind: "vocals", label: "Vocals" },
  { kind: "drums", label: "Drums" },
  { kind: "bass", label: "Bass" },
  { kind: "other", label: "Other" },
];

function stemLaneState(clip: ArrangementClip, kind: StemKind): StemLaneState {
  return clip.stem_states?.[kind] ?? { muted: 0, solo: 0 };
}

function audibleStemKinds(clip: ArrangementClip): StemKind[] {
  const soloed = stemDefinitions
    .filter(({ kind }) => Boolean(stemLaneState(clip, kind).solo))
    .map(({ kind }) => kind);
  return soloed.length > 0
    ? soloed
    : stemDefinitions
      .filter(({ kind }) => !stemLaneState(clip, kind).muted)
      .map(({ kind }) => kind);
}

const camelotMinorPitchClasses = [8, 3, 10, 5, 0, 7, 2, 9, 4, 11, 6, 1];
const camelotMajorPitchClasses = [11, 6, 1, 8, 3, 10, 5, 0, 7, 2, 9, 4];
const notePitchClasses: Record<string, number> = {
  C: 0, "C#": 1, DB: 1, D: 2, "D#": 3, EB: 3, E: 4,
  F: 5, "F#": 6, GB: 6, G: 7, "G#": 8, AB: 8, A: 9,
  "A#": 10, BB: 10, B: 11,
};
const sharpNoteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

type ParsedMusicalKey = {
  pitchClass: number;
  mode: "major" | "minor";
  format: "camelot" | "standard";
};

function parseMusicalKey(value: string): ParsedMusicalKey | null {
  const normalized = value.trim().replaceAll("♯", "#").replaceAll("♭", "b");
  const camelot = normalized.match(/^(1[0-2]|[1-9])([AB])$/i);
  if (camelot) {
    const number = Number(camelot[1]);
    const mode = camelot[2].toUpperCase() === "A" ? "minor" : "major";
    return {
      pitchClass: (mode === "minor" ? camelotMinorPitchClasses : camelotMajorPitchClasses)[number - 1],
      mode,
      format: "camelot",
    };
  }
  const standard = normalized.match(/^([A-Ga-g])([#b]?)(?:\s*(maj(?:or)?|min(?:or)?|m))?$/i);
  if (!standard) return null;
  const note = `${standard[1].toUpperCase()}${standard[2] === "b" ? "B" : standard[2]}`;
  const pitchClass = notePitchClasses[note];
  if (pitchClass == null) return null;
  const modeToken = (standard[3] ?? "major").toLowerCase();
  return { pitchClass, mode: modeToken.startsWith("m") && !modeToken.startsWith("maj") ? "minor" : "major", format: "standard" };
}

function transposeKeyLabel(sourceKey: string, semitones: number) {
  const parsed = parseMusicalKey(sourceKey);
  if (!parsed) return sourceKey || "Unknown";
  const pitchClass = ((parsed.pitchClass + Math.round(semitones)) % 12 + 12) % 12;
  if (parsed.format === "camelot") {
    const wheel = parsed.mode === "minor" ? camelotMinorPitchClasses : camelotMajorPitchClasses;
    return `${wheel.indexOf(pitchClass) + 1}${parsed.mode === "minor" ? "A" : "B"}`;
  }
  return `${sharpNoteNames[pitchClass]}${parsed.mode === "minor" ? "m" : ""}`;
}

function keyMatchPitch(selected: ArrangementClip, target: ArrangementClip) {
  const sourceKey = parseMusicalKey(selected.source_key);
  const targetKey = parseMusicalKey(target.source_key);
  if (!sourceKey || !targetKey) return null;
  const currentSourcePitch = ((sourceKey.pitchClass + Math.round(selected.pitch_semitones)) % 12 + 12) % 12;
  const currentTargetPitch = ((targetKey.pitchClass + Math.round(target.pitch_semitones)) % 12 + 12) % 12;
  const desiredPitch = sourceKey.mode === targetKey.mode
    ? currentTargetPitch
    : targetKey.mode === "minor"
      ? (currentTargetPitch + 3) % 12
      : (currentTargetPitch + 9) % 12;
  const delta = ((desiredPitch - currentSourcePitch + 18) % 12) - 6;
  const pitchSemitones = Math.max(-24, Math.min(24, selected.pitch_semitones + delta));
  return {
    pitchSemitones,
    delta,
    resultingKey: transposeKeyLabel(selected.source_key, pitchSemitones),
    targetKey: transposeKeyLabel(target.source_key, target.pitch_semitones),
    relativeModeMatch: sourceKey.mode !== targetKey.mode,
  };
}

function clipSourceLabel(kind: ArrangementClip["clip_kind"]) {
  if (kind === "song") return "Full song";
  if (kind === "rendered") return "Rendered edit";
  return `${kind.charAt(0).toUpperCase()}${kind.slice(1)} stem`;
}

function isDesktop() {
  return "__TAURI_INTERNALS__" in window;
}

function durationToSeconds(value: string) {
  const parts = value.split(":").map(Number);
  if (parts.length !== 2 || parts.some((part) => !Number.isFinite(part))) return 180;
  return parts[0] * 60 + parts[1];
}

function formatTime(seconds: number) {
  const safe = Math.max(0, Math.round(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function clipNeedsRender(clip: ArrangementClip) {
  return Boolean(
    clip.reversed
    || Math.abs(clip.pitch_semitones) > 0.001
    || Math.abs(clip.tempo_percent - 100) > 0.001
  );
}

function tempoFactor(clip: ArrangementClip) {
  return clip.tempo_percent / 100;
}

function clipTargetBpm(clip: ArrangementClip) {
  if (clip.source_bpm == null || clip.source_bpm <= 0) return null;
  return clip.source_bpm * tempoFactor(clip);
}

function tempoPercentForBpm(clip: ArrangementClip, targetBpm: number) {
  if (clip.source_bpm == null || clip.source_bpm <= 0 || !Number.isFinite(targetBpm)) return null;
  return Math.min(400, Math.max(25, (targetBpm / clip.source_bpm) * 100));
}

function retimedClipAtTempo(clip: ArrangementClip, tempoPercent: number) {
  const safeTempo = Math.min(400, Math.max(25, tempoPercent));
  const sourceSpan = clip.duration_seconds * tempoFactor(clip);
  return {
    ...clip,
    tempo_percent: safeTempo,
    duration_seconds: sourceSpan / (safeTempo / 100),
  };
}

function retimedClipAtEndBoundary(clip: ArrangementClip, requestedBoundary: number) {
  const sourceSpan = clip.duration_seconds * tempoFactor(clip);
  const minimumDuration = Math.max(
    0.05,
    clip.fade_in_seconds + clip.fade_out_seconds,
    sourceSpan / 4,
  );
  const maximumDuration = sourceSpan / 0.25;
  const requestedDuration = requestedBoundary - clip.start_seconds;
  const duration = Math.min(maximumDuration, Math.max(minimumDuration, requestedDuration));
  return retimedClipAtTempo(clip, (sourceSpan / duration) * 100);
}

function clipResizeBounds(clip: ArrangementClip, edge: ClipResizeEdge) {
  const start = clip.start_seconds;
  const end = start + clip.duration_seconds;
  const minimumDuration = Math.max(0.05, clip.fade_in_seconds + clip.fade_out_seconds);
  if (edge === "start") {
    const factor = tempoFactor(clip);
    const sourceSpan = clip.duration_seconds * factor;
    const availableBefore = clip.reversed
      ? (clip.source_duration_seconds - (clip.source_in_seconds + sourceSpan)) / factor
      : clip.source_in_seconds / factor;
    return {
      minimum: Math.max(0, start - Math.max(0, availableBefore)),
      maximum: end - minimumDuration,
    };
  }
  const factor = tempoFactor(clip);
  const sourceSpan = clip.duration_seconds * factor;
  const availableAfter = clip.reversed
    ? clip.source_in_seconds / factor
    : (clip.source_duration_seconds - (clip.source_in_seconds + sourceSpan)) / factor;
  return {
    minimum: start + minimumDuration,
    maximum: end + Math.max(0, availableAfter),
  };
}

function resizedClipAtBoundary(
  clip: ArrangementClip,
  edge: ClipResizeEdge,
  requestedBoundary: number,
) {
  const bounds = clipResizeBounds(clip, edge);
  const boundary = Math.min(bounds.maximum, Math.max(bounds.minimum, requestedBoundary));
  const start = clip.start_seconds;
  const end = start + clip.duration_seconds;
  if (edge === "start") {
    const delta = boundary - start;
    return {
      ...clip,
      start_seconds: boundary,
      source_in_seconds: clip.reversed ? clip.source_in_seconds : clip.source_in_seconds + delta * tempoFactor(clip),
      duration_seconds: clip.duration_seconds - delta,
    };
  }
  const delta = boundary - end;
  return {
    ...clip,
    source_in_seconds: clip.reversed ? clip.source_in_seconds - delta * tempoFactor(clip) : clip.source_in_seconds,
    duration_seconds: clip.duration_seconds + delta,
  };
}

function waveformResponseScale(clip: ArrangementClip, masterGainDb = 0) {
  const toneEnergyDb = (clip.eq_low_db + clip.eq_mid_db + clip.eq_high_db) / 8;
  const effectiveDb = clip.gain_db + masterGainDb + toneEnergyDb;
  return Math.min(1.5, Math.max(0.08, 0.62 * Math.pow(10, effectiveDb / 20)));
}

function WaveformShape({
  seed,
  muted = false,
  responseScale = 1,
}: {
  seed: number;
  muted?: boolean;
  responseScale?: number;
}) {
  return (
    <div className={`arrangement-wave ${muted ? "muted" : ""}`} aria-hidden="true">
      {Array.from({ length: 144 }, (_, index) => {
        const phrase = Math.abs(Math.sin((index + seed * 7) * 0.11));
        const transient = ((index * 29 + seed * 13) % 41) / 41;
        const height = 9 + Math.round((phrase * 0.68 + transient * 0.32) * 88);
        return <i key={index} style={{ height: `${Math.min(100, height * responseScale)}%` }} />;
      })}
    </div>
  );
}

function ClipWaveform({
  clip,
  zoom,
  source,
  preparedSource,
  masterGainDb,
}: {
  clip: ArrangementClip;
  zoom: number;
  source?: string | null;
  preparedSource?: string | null;
  masterGainDb: number;
}) {
  const responseScale = waveformResponseScale(clip, masterGainDb);
  if (preparedSource) {
    const preparedMask = `url("${preparedSource.replaceAll('"', '%22')}")`;
    return (
      <span className={`arrangement-wave-real ${clip.muted ? "muted" : ""}`} aria-hidden="true">
        <i style={{
          width: "100%",
          left: 0,
          WebkitMaskImage: preparedMask,
          maskImage: preparedMask,
          transform: `scaleY(${responseScale})`,
        }} />
      </span>
    );
  }
  if (!source) return <WaveformShape seed={clip.track_id} muted={Boolean(clip.muted)} responseScale={responseScale} />;
  const factor = tempoFactor(clip);
  const sourceWidth = Math.max(1, (clip.source_duration_seconds / factor) * zoom);
  const sourceLeft = -(clip.source_in_seconds / factor) * zoom;
  const mask = `url("${source.replaceAll('"', '%22')}")`;
  return (
    <span className={`arrangement-wave-real ${clip.reversed ? "reversed" : ""} ${clip.muted ? "muted" : ""}`} aria-hidden="true">
      <i style={{
        width: sourceWidth,
        left: sourceLeft,
        WebkitMaskImage: mask,
        maskImage: mask,
        transform: `scaleY(${responseScale})`,
      }} />
    </span>
  );
}

function browserPayload(tracks: ArrangementLibraryTrack[]): ArrangementPayload {
  const sample = tracks.slice(0, 3);
  return {
    project: {
      id: 1,
      name: "Sunset into peak",
      tempo: 120,
      musical_key: "8A",
      time_signature_numerator: 4,
      time_signature_denominator: 4,
      snap_enabled: 1,
      snap_beats: 1,
      selection_start_seconds: 40,
      selection_end_seconds: 72,
      selection_loop_enabled: 0,
      master_gain_db: 0,
      master_limiter_enabled: 1,
      master_low_eq_db: 0,
      master_mid_eq_db: 0,
      master_high_eq_db: 0,
      master_stereo_width: 1,
      target_lufs: -14,
      updated_at: new Date().toISOString(),
    },
    clips: sample.map((track, index) => ({
      id: index + 1,
      project_id: 1,
      track_id: track.id,
      clip_kind: "song",
      title: track.title,
      artist: track.artist,
      path: track.path ?? "",
      source_bpm: track.bpm,
      source_key: track.key,
      source_duration_seconds: durationToSeconds(track.duration),
      channel: index + 1,
      start_seconds: index * 82,
      source_in_seconds: 0,
      duration_seconds: durationToSeconds(track.duration),
      gain_db: 0,
      pan: 0,
      pitch_semitones: 0,
      tempo_percent: 100,
      color: channelColors[index],
      expanded: index === 0 ? 1 : 0,
      locked: 0,
      muted: 0,
      solo: 0,
      loop_enabled: 0,
      reversed: 0,
      fade_in_seconds: 0,
      fade_out_seconds: 0,
      eq_low_db: 0,
      eq_mid_db: 0,
      eq_high_db: 0,
      highpass_hz: 20,
      lowpass_hz: 20000,
      compressor_enabled: 0,
      compressor_threshold_db: -18,
      compressor_ratio: 4,
      group_id: null,
      stem_states: {},
    })),
    markers: [
      { id: 1, project_id: 1, marker_kind: "marker", name: "First transition", start_seconds: 64, end_seconds: null, color: "violet" },
      { id: 2, project_id: 1, marker_kind: "section", name: "Build", start_seconds: 90, end_seconds: 150, color: "cyan" },
    ],
    can_undo: false,
    can_redo: false,
  };
}

export function ArrangementWorkspace({ tracks }: ArrangementWorkspaceProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [payload, setPayload] = useState<ArrangementPayload | null>(() => isDesktop() ? null : browserPayload(tracks));
  const [selectedClipId, setSelectedClipId] = useState<number | null>(1);
  const [selectedClipIds, setSelectedClipIds] = useState<number[]>([1]);
  const [selectedMarkerId, setSelectedMarkerId] = useState<number | null>(null);
  const [libraryQuery, setLibraryQuery] = useState("");
  const [targetChannel, setTargetChannel] = useState(1);
  const [zoom, setZoom] = useState(2.2);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Saved");
  const [error, setError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [liveMeterDb, setLiveMeterDb] = useState(-60);
  const [channelMeterDb, setChannelMeterDb] = useState([-60, -60, -60, -60]);
  const [activeAuditionCount, setActiveAuditionCount] = useState(0);
  const [timelinePosition, setTimelinePosition] = useState(0);
  const [crossfadeTargetId, setCrossfadeTargetId] = useState<number | null>(null);
  const [keyMatchTargetId, setKeyMatchTargetId] = useState<number | null>(null);
  const [stemTargetChannel, setStemTargetChannel] = useState(1);
  const [waveformSources, setWaveformSources] = useState<Record<number, string | null>>({});
  const [stemStatus, setStemStatus] = useState<StemStatusPayload | null>(() => isDesktop() ? null : {
    capability: {
      available: false,
      engine: "Demucs",
      version: "",
      default_model: "htdemucs",
      message: "Demucs is not installed in Decksmith's isolated Python environment.",
    },
    model: "htdemucs",
    jobs: [],
    stems: [],
    ready_track_ids: [],
  });
  const [stemProgress, setStemProgress] = useState<StemProgressEvent["data"] | null>(null);
  const [separatingTrackId, setSeparatingTrackId] = useState<number | null>(null);
  const [previewingStemKind, setPreviewingStemKind] = useState<StemKind | null>(null);
  const [renderStatus, setRenderStatus] = useState<RenderStatusPayload | null>(() => isDesktop() ? null : {
    capability: {
      available: false,
      engine: "FFmpeg",
      version: "",
      message: "Processed clip rendering is available in the desktop app.",
    },
    jobs: [],
    renders: [],
    ready_clip_ids: [],
  });
  const [renderProgress, setRenderProgress] = useState<RenderProgressEvent["data"] | null>(null);
  const [renderingClipId, setRenderingClipId] = useState<number | null>(null);
  const [exportingFormat, setExportingFormat] = useState<"wav" | "mp3" | null>(null);
  const [lastAudioExport, setLastAudioExport] = useState<AudioExportResult | null>(null);
  const [audioExportHistory, setAudioExportHistory] = useState<AudioExportResult[]>([]);
  const [loudnessTargetedExport, setLoudnessTargetedExport] = useState(false);
  const [smartRenderReport, setSmartRenderReport] = useState<SmartRenderReport | null>(null);
  const [smartRenderRunning, setSmartRenderRunning] = useState(false);
  const audioContextRef = useRef<OutputClockAudioContext | null>(null);
  const decodedAudioRef = useRef<Map<string, Promise<AudioBuffer>>>(new Map());
  const scheduledAudioRef = useRef<ScheduledAudioVoice[]>([]);
  const scheduledOutputRef = useRef<AudioNode[]>([]);
  const scheduledMasterRef = useRef<ScheduledMasterControls | null>(null);
  const payloadRef = useRef(payload);
  const masterAnalyserRef = useRef<AnalyserNode | null>(null);
  const channelAnalyserRefs = useRef<AnalyserNode[]>([]);
  const stemPreviewAudioRef = useRef<HTMLAudioElement | null>(null);
  const auditionStartToken = useRef(0);
  const auditionStarting = useRef(false);
  const lastAuditionUiUpdate = useRef(0);
  const lastTimelinePaint = useRef(0);
  const auditionFrame = useRef<number | null>(null);
  const auditionAnchor = useRef({ contextTime: 0, time: 0 });
  const arrangementPlayheadRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(zoom);
  const timelineScrollRef = useRef<HTMLDivElement>(null);
  const pinchZoomStart = useRef(zoom);
  const draggedClip = useRef<number | null>(null);
  const draggedTrack = useRef<number | null>(null);
  const draggedStem = useRef<{ sourceClipId: number; stemKind: StemKind } | null>(null);
  const suppressClipClick = useRef(false);
  const renderClipKey = (payload?.clips ?? [])
    .map((clip) => [
      clip.id,
      clip.clip_kind,
      clip.source_in_seconds,
      clip.duration_seconds,
      clip.tempo_percent,
      clip.pitch_semitones,
      clip.reversed,
      ...stemDefinitions.map(({ kind }) => {
        const state = stemLaneState(clip, kind);
        return `${kind}-${state.muted}-${state.solo}`;
      }),
    ].join(":"))
    .join("|");
  zoomRef.current = zoom;
  payloadRef.current = payload;

  useEffect(() => {
    if (!isDesktop()) return;
    invoke<ProjectSummary[]>("load_arrangement_projects")
      .then(async (items) => {
        setProjects(items);
        if (items.length > 0) {
          const loaded = await invoke<ArrangementPayload>("load_arrangement_project", { projectId: items[0].id });
          setPayload(loaded);
          setSelectedClipId(loaded.clips[0]?.id ?? null);
          setSelectedClipIds(loaded.clips[0] ? [loaded.clips[0].id] : []);
        }
      })
      .catch((reason) => setError(String(reason)));
  }, []);
  useEffect(() => {
    if (!isDesktop() || !payload?.project.id) return;
    let disposed = false;
    Promise.all([
      invoke<SmartRenderReport | null>("load_latest_arrangement_audit", { projectId: payload.project.id }),
      invoke<AudioExportResult[]>("load_arrangement_export_history", { projectId: payload.project.id }),
    ]).then(([audit, exports]) => {
      if (disposed) return;
      setSmartRenderReport(audit?.fresh ? audit : null);
      setAudioExportHistory(exports);
      setLastAudioExport(exports[0] ?? null);
      setLoudnessTargetedExport(false);
    }).catch((reason) => {
      if (!disposed) setError(String(reason));
    });
    return () => { disposed = true; };
  }, [payload?.project.id]);
  useEffect(() => {
    if (!isDesktop() || !payload) return;
    let disposed = false;
    const clipIds = payload.clips.map((clip) => clip.id);
    setRenderStatus(null);
    invoke<RenderStatusPayload>("load_render_status", { clipIds })
      .then((next) => {
        if (disposed) return;
        const activePaths = new Set(next.renders.map((render) => render.path));
        for (const path of decodedAudioRef.current.keys()) {
          if (!activePaths.has(path)) decodedAudioRef.current.delete(path);
        }
        setRenderStatus(next);
      })
      .catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [renderClipKey]);
  useEffect(() => {
    if (!isDesktop()) return;
    let disposed = false;
    let removeListener: (() => void) | undefined;
    listen<RenderProgressEvent>("render-progress", (event) => {
      if (!disposed) setRenderProgress(event.payload.data);
    }).then((unlisten) => {
      if (disposed) unlisten();
      else removeListener = unlisten;
    });
    return () => {
      disposed = true;
      removeListener?.();
    };
  }, []);
  useEffect(() => {
    if (
      !isDesktop()
      || !payload
      || !renderStatus?.capability.available
      || renderingClipId != null
    ) return;
    const pending = payload.clips.find((clip) => (
      !renderStatus.ready_clip_ids.includes(clip.id)
      && !renderStatus.jobs.some((job) => (
        job.clip_id === clip.id && !job.stale && job.status === "failed"
      ))
    ));
    if (pending) void renderClipPreview(pending);
  }, [
    renderClipKey,
    renderingClipId,
    renderStatus?.capability.available,
    renderStatus?.ready_clip_ids.join(","),
    renderStatus?.jobs.map((job) => `${job.clip_id}:${job.status}:${job.stale}`).join("|"),
  ]);

  const selectedClip = payload?.clips.find((clip) => clip.id === selectedClipId) ?? null;
  const selectedClips = payload?.clips.filter((clip) => selectedClipIds.includes(clip.id)) ?? [];
  const selectedMarker = payload?.markers.find((marker) => marker.id === selectedMarkerId) ?? null;
  const keyMatchCandidates = selectedClip && payload
    ? payload.clips.filter((clip) => clip.id !== selectedClip.id && parseMusicalKey(clip.source_key))
    : [];
  const keyMatchTarget = keyMatchCandidates.find((clip) => clip.id === keyMatchTargetId) ?? keyMatchCandidates[0] ?? null;
  const selectedKeyMatch = selectedClip && keyMatchTarget ? keyMatchPitch(selectedClip, keyMatchTarget) : null;
  const overlapCandidates = selectedClip && payload
    ? payload.clips.filter((clip) => (
      clip.id !== selectedClip.id
      && Math.abs(clip.start_seconds - selectedClip.start_seconds) >= 0.001
      && Math.max(clip.start_seconds, selectedClip.start_seconds)
        < Math.min(clip.start_seconds + clip.duration_seconds, selectedClip.start_seconds + selectedClip.duration_seconds)
    ))
    : [];
  const overlapKey = overlapCandidates
    .map((clip) => `${clip.id}:${clip.start_seconds}:${clip.duration_seconds}`)
    .join("|");
  const estimatedPeakDb = useMemo(() => {
    if (!payload) return -Infinity;
    const events = payload.clips
      .filter((clip) => !clip.muted)
      .flatMap((clip) => {
        const level = Math.pow(10, clip.gain_db / 20);
        return [
          { time: clip.start_seconds, delta: level },
          { time: clip.start_seconds + clip.duration_seconds, delta: -level },
        ];
      })
      .sort((left, right) => left.time - right.time || left.delta - right.delta);
    let active = 0;
    let peak = 0;
    for (const event of events) {
      active += event.delta;
      peak = Math.max(peak, active);
    }
    return peak > 0 ? 20 * Math.log10(peak) + payload.project.master_gain_db : -Infinity;
  }, [payload]);
  const renderPendingCount = payload?.clips.filter((clip) => (
    !renderStatus?.ready_clip_ids.includes(clip.id)
  )).length ?? 0;
  const preparedWaveformSources = useMemo(() => Object.fromEntries(
    (renderStatus?.renders ?? []).map((render) => [
      render.clip_id,
      render.waveform_path ? convertFileSrc(render.waveform_path) : null,
    ]),
  ), [renderStatus]);
  const waveformTrackKey = Array.from(new Set((payload?.clips ?? []).map((clip) => clip.track_id)))
    .sort((left, right) => left - right)
    .join(",");
  useEffect(() => {
    if (!isDesktop() || !waveformTrackKey) return;
    let disposed = false;
    const trackIds = waveformTrackKey.split(",").map(Number);
    void (async () => {
      for (const trackId of trackIds) {
        if (Object.prototype.hasOwnProperty.call(waveformSources, trackId)) continue;
        try {
          const result = await invoke<{ path: string }>("generate_track_waveform", { trackId });
          if (!disposed) {
            setWaveformSources((items) => ({ ...items, [trackId]: convertFileSrc(result.path) }));
          }
        } catch {
          if (!disposed) setWaveformSources((items) => ({ ...items, [trackId]: null }));
        }
      }
    })();
    return () => { disposed = true; };
  }, [waveformTrackKey]);
  useEffect(() => {
    if (!isDesktop() || !waveformTrackKey) return;
    const trackIds = waveformTrackKey.split(",").map(Number);
    invoke<StemStatusPayload>("load_stem_status", { trackIds })
      .then(setStemStatus)
      .catch((reason) => setError(String(reason)));
  }, [waveformTrackKey]);
  useEffect(() => {
    if (!isDesktop()) return;
    let disposed = false;
    let removeListener: (() => void) | undefined;
    listen<StemProgressEvent>("stem-progress", (event) => {
      if (!disposed) setStemProgress(event.payload.data);
    }).then((unlisten) => {
      if (disposed) unlisten();
      else removeListener = unlisten;
    });
    return () => {
      disposed = true;
      removeListener?.();
    };
  }, []);
  useEffect(() => {
    if (!selectedClip) return;
    setCrossfadeTargetId(overlapCandidates[0]?.id ?? null);
    setKeyMatchTargetId((current) => (
      keyMatchCandidates.some((clip) => clip.id === current) ? current : keyMatchCandidates[0]?.id ?? null
    ));
    setStemTargetChannel(selectedClip.channel);
  }, [selectedClipId, selectedClip?.duration_seconds, overlapKey]);
  const filteredTracks = useMemo(() => {
    const query = libraryQuery.trim().toLowerCase();
    return tracks.filter((track) => !query || [track.title, track.artist, String(track.bpm), track.key]
      .some((value) => value.toLowerCase().includes(query)));
  }, [libraryQuery, tracks]);
  const timelineDuration = Math.max(
    360,
    ...((payload?.clips ?? []).map((clip) => clip.start_seconds + clip.duration_seconds + 45)),
    ...((payload?.markers ?? []).map((marker) => (marker.end_seconds ?? marker.start_seconds) + 45)),
  );
  const timelineWidth = timelineDuration * zoom;
  const rulerTicks = Array.from({ length: Math.ceil(timelineDuration / 30) + 1 }, (_, index) => index * 30);
  const splitOffset = selectedClip ? timelinePosition - selectedClip.start_seconds : null;
  const selectionStart = payload?.project.selection_start_seconds ?? null;
  const selectionEnd = payload?.project.selection_end_seconds ?? null;
  const hasSelection = selectionStart != null && selectionEnd != null && selectionEnd > selectionStart;
  const canSplitAtPlayhead = Boolean(
    selectedClip
    && !selectedClip.locked
    && splitOffset != null
    && splitOffset >= 0.05
    && splitOffset <= selectedClip.duration_seconds - 0.05,
  );
  const selectedStemAssets = selectedClip
    ? stemStatus?.stems.filter((stem) => stem.track_id === selectedClip.track_id) ?? []
    : [];
  const selectedStemJob = selectedClip
    ? stemStatus?.jobs.find((job) => job.track_id === selectedClip.track_id && !job.stale) ?? null
    : null;
  const selectedStemProgress = selectedClip && stemProgress?.track_id === selectedClip.track_id
    ? stemProgress
    : null;
  const selectedStemsReady = selectedStemAssets.length === 4;
  const selectedStemBusy = selectedClip != null && separatingTrackId === selectedClip.track_id;
  const selectedRender = selectedClip
    ? renderStatus?.renders.find((render) => render.clip_id === selectedClip.id) ?? null
    : null;
  const selectedRenderJob = selectedClip
    ? renderStatus?.jobs.find((job) => job.clip_id === selectedClip.id && !job.stale) ?? null
    : null;
  const selectedRenderProgress = selectedClip && renderProgress?.clip_id === selectedClip.id
    ? renderProgress
    : null;
  const selectedRenderBusy = selectedClip != null && renderingClipId === selectedClip.id;

  useEffect(() => {
    const scroll = timelineScrollRef.current;
    if (!scroll) return;
    const applyAnchoredZoom = (nextZoom: number, clientX: number) => {
      const bounds = scroll.getBoundingClientRect();
      const pointerX = clientX - bounds.left;
      const timelineX = Math.max(0, scroll.scrollLeft + pointerX - 112);
      const currentZoom = zoomRef.current;
      const timeUnderPointer = timelineX / currentZoom;
      if (Math.abs(nextZoom - currentZoom) < 0.001) return;
      setZoom(nextZoom);
      zoomRef.current = nextZoom;
      requestAnimationFrame(() => {
        scroll.scrollLeft = Math.max(0, 112 + timeUnderPointer * nextZoom - pointerX);
      });
    };
    const zoomFromTrackpad = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey && !event.altKey) return;
      event.preventDefault();
      const nextZoom = Math.min(maximumTimelineZoom, Math.max(minimumTimelineZoom, zoomRef.current * Math.exp(-event.deltaY * 0.0025)));
      applyAnchoredZoom(nextZoom, event.clientX);
    };
    const startPinch = (event: Event) => {
      event.preventDefault();
      pinchZoomStart.current = zoomRef.current;
    };
    const continuePinch = (event: Event) => {
      event.preventDefault();
      const gesture = event as Event & { scale?: number; clientX?: number };
      const scale = Number.isFinite(gesture.scale) ? gesture.scale ?? 1 : 1;
      const bounds = scroll.getBoundingClientRect();
      const nextZoom = Math.min(maximumTimelineZoom, Math.max(minimumTimelineZoom, pinchZoomStart.current * scale));
      applyAnchoredZoom(nextZoom, gesture.clientX ?? bounds.left + bounds.width / 2);
    };
    scroll.addEventListener("wheel", zoomFromTrackpad, { passive: false });
    scroll.addEventListener("gesturestart", startPinch, { passive: false });
    scroll.addEventListener("gesturechange", continuePinch, { passive: false });
    return () => {
      scroll.removeEventListener("wheel", zoomFromTrackpad);
      scroll.removeEventListener("gesturestart", startPinch);
      scroll.removeEventListener("gesturechange", continuePinch);
    };
  }, [payload?.project.id]);

  function audioContext() {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext({ latencyHint: "interactive" }) as OutputClockAudioContext;
    }
    return audioContextRef.current;
  }

  function decodedAudio(path: string) {
    const cached = decodedAudioRef.current.get(path);
    if (cached) return cached;
    const context = audioContext();
    const pending = fetch(convertFileSrc(path))
      .then((response) => {
        if (!response.ok) throw new Error(`Could not load prepared audio (${response.status}).`);
        return response.arrayBuffer();
      })
      .then((data) => context.decodeAudioData(data))
      .catch((reason) => {
        decodedAudioRef.current.delete(path);
        throw reason;
      });
    decodedAudioRef.current.set(path, pending);
    return pending;
  }

  function stopScheduledAudio() {
    for (const voice of scheduledAudioRef.current) {
      try { voice.source.stop(); } catch { /* The source may already have ended. */ }
      voice.source.disconnect();
      voice.gain.disconnect();
    }
    scheduledAudioRef.current = [];
    for (const node of scheduledOutputRef.current) node.disconnect();
    scheduledOutputRef.current = [];
    scheduledMasterRef.current = null;
    masterAnalyserRef.current = null;
    channelAnalyserRefs.current = [];
  }

  function stopStemPreview() {
    stemPreviewAudioRef.current?.pause();
    stemPreviewAudioRef.current = null;
    setPreviewingStemKind(null);
  }

  function audibleContextTime(context: OutputClockAudioContext) {
    const timestamp = context.getOutputTimestamp?.();
    const timestampContextTime = Number(timestamp?.contextTime);
    const timestampPerformanceTime = Number(timestamp?.performanceTime);
    if (
      timestamp
      && Number.isFinite(timestampContextTime)
      && Number.isFinite(timestampPerformanceTime)
      && timestampPerformanceTime > 0
    ) {
      return timestampContextTime + (performance.now() - timestampPerformanceTime) / 1000;
    }
    const outputLatency = Number.isFinite(context.outputLatency)
      ? context.outputLatency ?? 0
      : context.baseLatency;
    return context.currentTime - Math.max(0, outputLatency || 0);
  }

  function clipLevelAt(clip: ArrangementClip, localTime: number) {
    const fadeIn = clip.fade_in_seconds > 0 ? Math.min(1, localTime / clip.fade_in_seconds) : 1;
    const fadeOut = clip.fade_out_seconds > 0
      ? Math.min(1, Math.max(0, (clip.duration_seconds - localTime) / clip.fade_out_seconds))
      : 1;
    return Math.pow(10, clip.gain_db / 20) * fadeIn * fadeOut;
  }

  function targetAudioParam(parameter: AudioParam, value: number, contextTime: number) {
    parameter.cancelScheduledValues(contextTime);
    parameter.setTargetAtTime(value, contextTime, 0.015);
  }

  function syncLiveAudio(nextPayload: ArrangementPayload) {
    const context = audioContextRef.current;
    if (!context || scheduledAudioRef.current.length === 0) return;
    const now = context.currentTime;
    const soloActive = nextPayload.clips.some((clip) => clip.solo);
    for (const voice of scheduledAudioRef.current) {
      const clip = nextPayload.clips.find((item) => item.id === voice.clipId);
      if (!clip) continue;
      const audible = !clip.muted && (!soloActive || Boolean(clip.solo));
      targetAudioParam(voice.gain.gain, audible ? Math.pow(10, clip.gain_db / 20) : 0, now);
      targetAudioParam(voice.panner.pan, clip.pan, now);
      targetAudioParam(voice.lowEq.gain, clip.eq_low_db, now);
      targetAudioParam(voice.midEq.gain, clip.eq_mid_db, now);
      targetAudioParam(voice.highEq.gain, clip.eq_high_db, now);
      targetAudioParam(voice.highpass.frequency, clip.highpass_hz, now);
      targetAudioParam(voice.lowpass.frequency, clip.lowpass_hz, now);
      targetAudioParam(
        voice.compressor.threshold,
        clip.compressor_enabled ? clip.compressor_threshold_db : 0,
        now,
      );
      targetAudioParam(
        voice.compressor.ratio,
        clip.compressor_enabled ? clip.compressor_ratio : 1,
        now,
      );
    }
    const master = scheduledMasterRef.current;
    if (!master) return;
    const project = nextPayload.project;
    targetAudioParam(master.gain.gain, Math.pow(10, project.master_gain_db / 20), now);
    targetAudioParam(master.lowEq.gain, project.master_low_eq_db, now);
    targetAudioParam(master.midEq.gain, project.master_mid_eq_db, now);
    targetAudioParam(master.highEq.gain, project.master_high_eq_db, now);
    targetAudioParam(master.leftToSide.gain, 0.5 * project.master_stereo_width, now);
    targetAudioParam(master.rightToSide.gain, -0.5 * project.master_stereo_width, now);
    targetAudioParam(master.limiter.threshold, project.master_limiter_enabled ? -1 : 0, now);
    targetAudioParam(master.limiter.ratio, project.master_limiter_enabled ? 20 : 1, now);
  }

  function updateTimelineMeters(time: number) {
    const currentPayload = payloadRef.current;
    if (!currentPayload) return;
    const soloActive = currentPayload.clips.some((clip) => clip.solo);
    const channelLevels = [0, 0, 0, 0];
    let combinedLevel = 0;
    let activeCount = 0;
    for (const clip of currentPayload.clips) {
      const localTime = time - clip.start_seconds;
      if (
        localTime < 0
        || localTime >= clip.duration_seconds
        || clip.muted
        || (soloActive && !clip.solo)
        || !renderStatus?.ready_clip_ids.includes(clip.id)
      ) continue;
      const level = clipLevelAt(clip, localTime) * Math.pow(10, currentPayload.project.master_gain_db / 20);
      combinedLevel += level;
      channelLevels[clip.channel - 1] += level;
      activeCount += 1;
    }
    if (masterAnalyserRef.current) {
      setLiveMeterDb(analyserLevelDb(masterAnalyserRef.current));
      setChannelMeterDb(channelAnalyserRefs.current.map((analyser) => analyserLevelDb(analyser)));
    } else {
      setLiveMeterDb(combinedLevel <= 0 ? -60 : Math.max(-60, 20 * Math.log10(combinedLevel)));
      setChannelMeterDb(channelLevels.map((level) => (
        level <= 0 ? -60 : Math.max(-60, 20 * Math.log10(level))
      )));
    }
    setActiveAuditionCount(activeCount);
  }

  function pauseTimelineAudition() {
    auditionStartToken.current += 1;
    auditionStarting.current = false;
    if (auditionFrame.current != null) cancelAnimationFrame(auditionFrame.current);
    auditionFrame.current = null;
    stopScheduledAudio();
    setPreviewing(false);
    setLiveMeterDb(-60);
    setChannelMeterDb([-60, -60, -60, -60]);
    setActiveAuditionCount(0);
  }

  async function startTimelineAudition(startOverride?: number) {
    if (!payload || !renderStatus?.renders.length || auditionStarting.current) return;
    stopStemPreview();
    auditionStarting.current = true;
    const token = auditionStartToken.current + 1;
    auditionStartToken.current = token;
    setStatus("Cueing audio");
    setError(null);
    let start = startOverride ?? timelinePosition;
    if (payload.project.selection_loop_enabled && hasSelection && selectionStart != null && selectionEnd != null) {
      if (start < selectionStart || start >= selectionEnd) start = selectionStart;
    }
    const soloActive = payload.clips.some((clip) => clip.solo);
    const playable = payload.clips.flatMap((clip) => {
      const render = renderStatus.renders.find((item) => item.clip_id === clip.id);
      if (
        !render
        || clip.muted
        || (soloActive && !clip.solo)
        || clip.start_seconds + clip.duration_seconds <= start
      ) return [];
      return [{ clip, render }];
    });
    if (playable.length === 0) {
      auditionStarting.current = false;
      setStatus("Saved");
      return;
    }
    const context = audioContext();
    try {
      await context.resume();
      setStatus("Loading prepared audio");
      const buffers = new Map<string, AudioBuffer>();
      await Promise.all(playable.map(async ({ render }) => {
        buffers.set(render.path, await decodedAudio(render.path));
      }));
      if (token !== auditionStartToken.current) return;
      stopScheduledAudio();
      const scheduleTime = context.currentTime + 0.08;
      const master = context.createGain();
      master.gain.value = Math.pow(10, payload.project.master_gain_db / 20);
      const masterEq = createThreeBandEq(
        context,
        payload.project.master_low_eq_db,
        payload.project.master_mid_eq_db,
        payload.project.master_high_eq_db,
      );
      const stereoWidth = createStereoWidth(context, payload.project.master_stereo_width);
      master.connect(masterEq.input);
      masterEq.output.connect(stereoWidth.input);
      scheduledOutputRef.current.push(master, ...masterEq.nodes, ...stereoWidth.nodes);
      const masterAnalyser = context.createAnalyser();
      masterAnalyser.fftSize = 1024;
      masterAnalyser.smoothingTimeConstant = 0.65;
      masterAnalyserRef.current = masterAnalyser;
      const limiter = context.createDynamicsCompressor();
      limiter.threshold.value = payload.project.master_limiter_enabled ? -1 : 0;
      limiter.knee.value = 0;
      limiter.ratio.value = payload.project.master_limiter_enabled ? 20 : 1;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.1;
      stereoWidth.output.connect(limiter);
      limiter.connect(masterAnalyser);
      scheduledOutputRef.current.push(limiter);
      scheduledMasterRef.current = {
        gain: master,
        lowEq: masterEq.low,
        midEq: masterEq.mid,
        highEq: masterEq.high,
        leftToSide: stereoWidth.leftToSide,
        rightToSide: stereoWidth.rightToSide,
        limiter,
      };
      masterAnalyser.connect(context.destination);
      const channelAnalysers: AnalyserNode[] = [];
      const channelOutputs = Array.from({ length: 4 }, () => {
        const channel = context.createGain();
        const analyser = context.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.65;
        channel.connect(analyser);
        analyser.connect(master);
        channelAnalysers.push(analyser);
        scheduledOutputRef.current.push(channel, analyser);
        return channel;
      });
      channelAnalyserRefs.current = channelAnalysers;
      scheduledOutputRef.current.push(masterAnalyser);
      for (const { clip, render } of playable) {
        const buffer = buffers.get(render.path);
        if (!buffer) continue;
        const timelineDelay = Math.max(0, clip.start_seconds - start);
        const localOffset = Math.max(0, start - clip.start_seconds);
        const remaining = Math.min(
          clip.duration_seconds - localOffset,
          buffer.duration - localOffset,
        );
        if (remaining <= 0.001) continue;
        const when = scheduleTime + timelineDelay;
        const source = context.createBufferSource();
        source.buffer = buffer;
        const gain = context.createGain();
        const envelope = context.createGain();
        const panner = context.createStereoPanner();
        const clipEq = createThreeBandEq(
          context,
          clip.eq_low_db,
          clip.eq_mid_db,
          clip.eq_high_db,
        );
        const highpass = context.createBiquadFilter();
        highpass.type = "highpass";
        highpass.frequency.value = clip.highpass_hz;
        highpass.Q.value = 0.707;
        const lowpass = context.createBiquadFilter();
        lowpass.type = "lowpass";
        lowpass.frequency.value = clip.lowpass_hz;
        lowpass.Q.value = 0.707;
        panner.pan.value = clip.pan;
        const baseLevel = Math.pow(10, clip.gain_db / 20);
        const soloAllowsClip = !soloActive || Boolean(clip.solo);
        gain.gain.value = !clip.muted && soloAllowsClip ? baseLevel : 0;
        const initialEnvelope = clipLevelAt(clip, localOffset) / Math.max(0.000001, baseLevel);
        envelope.gain.setValueAtTime(initialEnvelope, when);
        if (clip.fade_in_seconds > localOffset) {
          envelope.gain.linearRampToValueAtTime(1, when + clip.fade_in_seconds - localOffset);
        }
        const fadeOutStart = clip.duration_seconds - clip.fade_out_seconds;
        if (clip.fade_out_seconds > 0 && fadeOutStart >= localOffset) {
          envelope.gain.setValueAtTime(1, when + fadeOutStart - localOffset);
          envelope.gain.linearRampToValueAtTime(0, when + clip.duration_seconds - localOffset);
        }
        source.connect(clipEq.input);
        clipEq.output.connect(highpass);
        highpass.connect(lowpass);
        const compressor = context.createDynamicsCompressor();
        compressor.threshold.value = clip.compressor_enabled ? clip.compressor_threshold_db : 0;
        compressor.knee.value = 12;
        compressor.ratio.value = clip.compressor_enabled ? clip.compressor_ratio : 1;
        compressor.attack.value = 0.003;
        compressor.release.value = 0.25;
        lowpass.connect(compressor);
        compressor.connect(envelope);
        envelope.connect(gain);
        gain.connect(panner);
        panner.connect(channelOutputs[clip.channel - 1]);
        scheduledOutputRef.current.push(
          ...clipEq.nodes, highpass, lowpass, compressor, envelope, panner,
        );
        source.start(when, localOffset, remaining);
        scheduledAudioRef.current.push({
          clipId: clip.id,
          source,
          gain,
          envelope,
          panner,
          lowEq: clipEq.low,
          midEq: clipEq.mid,
          highEq: clipEq.high,
          highpass,
          lowpass,
          compressor,
        });
      }
      auditionAnchor.current = { contextTime: scheduleTime, time: start };
    } catch (reason) {
      if (token === auditionStartToken.current) {
        setError(`Audio preview could not start: ${String(reason)}`);
        setStatus("Saved");
        pauseTimelineAudition();
      }
      return;
    }
    if (token !== auditionStartToken.current) return;
    lastAuditionUiUpdate.current = 0;
    lastTimelinePaint.current = 0;
    auditionStarting.current = false;
    setStatus("Saved");
    setTimelinePosition(start);
    setPreviewing(true);
    const tick = () => {
      if (token !== auditionStartToken.current) return;
      const now = performance.now();
      const heardContextTime = audibleContextTime(context);
      let next = auditionAnchor.current.time
        + Math.max(0, heardContextTime - auditionAnchor.current.contextTime);
      if (payload.project.selection_loop_enabled && hasSelection && selectionStart != null && selectionEnd != null && next >= selectionEnd) {
        pauseTimelineAudition();
        setTimelinePosition(selectionStart);
        void startTimelineAudition(selectionStart);
        return;
      }
      if (arrangementPlayheadRef.current) {
        arrangementPlayheadRef.current.style.left = `${112 + next * zoomRef.current}px`;
      }
      if (next >= timelineDuration) {
        pauseTimelineAudition();
        return;
      }
      if (now - lastTimelinePaint.current >= 100) {
        lastTimelinePaint.current = now;
        setTimelinePosition(next);
        updateTimelineMeters(next);
      }
      auditionFrame.current = requestAnimationFrame(tick);
    };
    auditionFrame.current = requestAnimationFrame(tick);
  }

  function toggleTimelineAudition() {
    if (previewing || auditionStarting.current) pauseTimelineAudition();
    else void startTimelineAudition();
  }

  useEffect(() => () => {
    pauseTimelineAudition();
    stopStemPreview();
    decodedAudioRef.current.clear();
    void audioContextRef.current?.close();
    audioContextRef.current = null;
  }, []);

  async function refreshProjectList() {
    if (!isDesktop()) return;
    setProjects(await invoke<ProjectSummary[]>("load_arrangement_projects"));
  }

  function applyPayload(next: ArrangementPayload) {
    payloadRef.current = next;
    syncLiveAudio(next);
    setSmartRenderReport(null);
    setLoudnessTargetedExport(false);
    setPayload(next);
    if (next.selected_clip_id) {
      setSelectedClipId(next.selected_clip_id);
      setSelectedClipIds([next.selected_clip_id]);
      setSelectedMarkerId(null);
    }
    if (next.selected_clip_ids?.length) {
      setSelectedClipIds(next.selected_clip_ids);
      setSelectedClipId(next.selected_clip_ids[0]);
      setSelectedMarkerId(null);
    }
    if (next.selected_marker_id) {
      setSelectedMarkerId(next.selected_marker_id);
      setSelectedClipId(null);
    }
    if (selectedClipId != null && !next.clips.some((clip) => clip.id === selectedClipId)) {
      setSelectedClipId(next.clips[0]?.id ?? null);
    }
    setSelectedClipIds((ids) => ids.filter((id) => next.clips.some((clip) => clip.id === id)));
    if (selectedMarkerId != null && !next.markers.some((marker) => marker.id === selectedMarkerId)) {
      setSelectedMarkerId(null);
    }
    setStatus("Saved");
    setError(null);
  }

  async function createProject() {
    pauseTimelineAudition();
    setBusy(true);
    setStatus("Creating");
    try {
      if (isDesktop()) {
        const next = await invoke<ArrangementPayload>("create_arrangement_project", { name: "Untitled arrangement", tempo: 120 });
        applyPayload(next);
        await refreshProjectList();
      } else {
        applyPayload(browserPayload(tracks));
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    } finally {
      setBusy(false);
    }
  }

  async function openProject(projectId: number) {
    if (!isDesktop()) return;
    pauseTimelineAudition();
    setBusy(true);
    try {
      const next = await invoke<ArrangementPayload>("load_arrangement_project", { projectId });
      applyPayload(next);
      setSelectedClipId(next.clips[0]?.id ?? null);
      setSelectedClipIds(next.clips[0] ? [next.clips[0].id] : []);
      setSelectedMarkerId(null);
      setTimelinePosition(0);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function saveProjectDetails(name: string, tempo: number) {
    if (!payload) return;
    setStatus("Saving");
    try {
      if (isDesktop()) {
        const next = await invoke<ArrangementPayload>("update_arrangement_project", {
          projectId: payload.project.id,
          name,
          tempo,
        });
        applyPayload(next);
        await refreshProjectList();
      } else {
        applyPayload({ ...payload, project: { ...payload.project, name, tempo } });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  function snapTime(seconds: number) {
    if (!payload?.project.snap_enabled) return Math.max(0, seconds);
    const gridSeconds = (60 / payload.project.tempo) * payload.project.snap_beats;
    return Math.max(0, Math.round(seconds / gridSeconds) * gridSeconds);
  }

  async function updateSnapSettings(changes: { snap_enabled?: number; snap_beats?: number }) {
    if (!payload) return;
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("update_arrangement_project", {
          projectId: payload.project.id,
          name: null,
          tempo: null,
          snapEnabled: changes.snap_enabled == null ? null : Boolean(changes.snap_enabled),
          snapBeats: changes.snap_beats ?? null,
        }));
      } else {
        applyPayload({ ...payload, project: { ...payload.project, ...changes } });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function updateSelection(start: number | null, end: number | null, loopEnabled: boolean) {
    if (!payload) return;
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("update_arrangement_selection", {
          projectId: payload.project.id,
          startSeconds: start,
          endSeconds: end,
          loopEnabled,
        }));
      } else {
        applyPayload({
          ...payload,
          project: {
            ...payload.project,
            selection_start_seconds: start,
            selection_end_seconds: end,
            selection_loop_enabled: Number(loopEnabled && start != null && end != null),
          },
        });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  function setSelectionBoundary(boundary: "start" | "end") {
    if (!payload) return;
    const defaultLength = (60 / payload.project.tempo) * 32;
    if (boundary === "start") {
      const end = selectionEnd != null && selectionEnd > timelinePosition
        ? selectionEnd
        : timelinePosition + defaultLength;
      void updateSelection(timelinePosition, end, Boolean(payload.project.selection_loop_enabled));
    } else {
      const start = selectionStart != null && selectionStart < timelinePosition
        ? selectionStart
        : Math.max(0, timelinePosition - defaultLength);
      if (timelinePosition <= start) {
        setError("Place the playhead after the selection start.");
        return;
      }
      void updateSelection(start, timelinePosition, Boolean(payload.project.selection_loop_enabled));
    }
  }

  function toggleSelectionLoop() {
    if (!payload) return;
    if (!hasSelection) {
      const length = (60 / payload.project.tempo) * 32;
      void updateSelection(timelinePosition, timelinePosition + length, true);
      return;
    }
    void updateSelection(selectionStart, selectionEnd, !payload.project.selection_loop_enabled);
  }

  async function undoProject() {
    if (!payload?.can_undo || !isDesktop()) return;
    pauseTimelineAudition();
    setStatus("Undoing");
    try {
      applyPayload(await invoke<ArrangementPayload>("undo_arrangement_project", { projectId: payload.project.id }));
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function redoProject() {
    if (!payload?.can_redo || !isDesktop()) return;
    pauseTimelineAudition();
    setStatus("Redoing");
    try {
      applyPayload(await invoke<ArrangementPayload>("redo_arrangement_project", { projectId: payload.project.id }));
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function exportProjectAudio(audioFormat: "wav" | "mp3") {
    if (!payload || !isDesktop() || exportingFormat || renderPendingCount > 0) return;
    const safeName = payload.project.name.replace(/[\\/:*?"<>|]+/g, "-").trim() || "Decksmith mix";
    const targetSuffix = loudnessTargetedExport ? ` · ${payload.project.target_lufs.toFixed(0)} LUFS` : "";
    const destination = await save({
      title: `Export ${audioFormat.toUpperCase()} mixdown`,
      defaultPath: `${safeName}${targetSuffix}.${audioFormat}`,
      filters: [{
        name: audioFormat === "wav" ? "WAV audio" : "MP3 audio",
        extensions: [audioFormat],
      }],
    });
    if (!destination) return;
    setExportingFormat(audioFormat);
    setStatus(`Exporting ${audioFormat.toUpperCase()}`);
    setError(null);
    try {
      const result = await invoke<AudioExportResult>("export_arrangement_audio", {
        projectId: payload.project.id,
        destination,
        audioFormat,
        loudnessTargeted: loudnessTargetedExport,
      });
      setLastAudioExport(result);
      setAudioExportHistory((history) => [result, ...history]);
      setStatus(`${audioFormat.toUpperCase()} exported`);
    } catch (reason) {
      setError(String(reason));
      setStatus("Export failed");
    } finally {
      setExportingFormat(null);
    }
  }

  async function runSmartRender() {
    if (!payload || !isDesktop() || smartRenderRunning || renderPendingCount > 0) return;
    pauseTimelineAudition();
    setSmartRenderRunning(true);
    setSmartRenderReport(null);
    setError(null);
    setStatus("Analysing final mix");
    try {
      const report = await invoke<SmartRenderReport>("audit_arrangement_project", {
        projectId: payload.project.id,
      });
      setSmartRenderReport(report);
      setStatus(report.status === "ready" ? "Smart Render passed" : "Smart Render complete");
    } catch (reason) {
      setError(String(reason));
      setStatus("Smart Render failed");
    } finally {
      setSmartRenderRunning(false);
    }
  }

  function revealSmartRenderIssue(issue: SmartRenderIssue) {
    if (issue.start_seconds != null) setTimelinePosition(issue.start_seconds);
    if (issue.clip_ids.length) {
      setSelectedClipIds(issue.clip_ids);
      setSelectedClipId(issue.clip_ids[0]);
      setSelectedMarkerId(null);
    }
  }

  async function updateMaster(changes: {
    master_gain_db?: number;
    master_limiter_enabled?: number;
    musical_key?: string;
    master_low_eq_db?: number;
    master_mid_eq_db?: number;
    master_high_eq_db?: number;
    master_stereo_width?: number;
    target_lufs?: number;
  }) {
    if (!payload) return;
    const optimistic = { ...payload, project: { ...payload.project, ...changes } };
    payloadRef.current = optimistic;
    setPayload(optimistic);
    syncLiveAudio(optimistic);
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("update_arrangement_project", {
          projectId: payload.project.id,
          masterGain: changes.master_gain_db ?? null,
          masterLimiter: changes.master_limiter_enabled == null ? null : Boolean(changes.master_limiter_enabled),
          musicalKey: changes.musical_key ?? null,
          masterLowEq: changes.master_low_eq_db ?? null,
          masterMidEq: changes.master_mid_eq_db ?? null,
          masterHighEq: changes.master_high_eq_db ?? null,
          masterWidth: changes.master_stereo_width ?? null,
          targetLufs: changes.target_lufs ?? null,
        }));
      } else {
        applyPayload({ ...payload, project: { ...payload.project, ...changes } });
      }
    } catch (reason) {
      payloadRef.current = payload;
      setPayload(payload);
      syncLiveAudio(payload);
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function groupSelectedClips() {
    if (!payload || selectedClipIds.length < 2) return;
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("group_arrangement_clips", { clipIds: selectedClipIds }));
      } else {
        const nextGroup = Math.max(0, ...payload.clips.map((clip) => clip.group_id ?? 0)) + 1;
        applyPayload({ ...payload, clips: payload.clips.map((clip) => selectedClipIds.includes(clip.id) ? { ...clip, group_id: nextGroup } : clip), selected_clip_ids: selectedClipIds });
      }
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function ungroupSelectedClips() {
    if (!payload || selectedClip?.group_id == null) return;
    const groupId = selectedClip.group_id;
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("ungroup_arrangement_clips", { projectId: payload.project.id, groupId }));
      } else {
        applyPayload({ ...payload, clips: payload.clips.map((clip) => clip.group_id === groupId ? { ...clip, group_id: null } : clip) });
      }
      setSelectedClipIds(selectedClip ? [selectedClip.id] : []);
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function batchUpdateSelected(changes: Record<string, string | number | boolean>) {
    if (!payload || selectedClipIds.length === 0) return;
    const normalized = Object.fromEntries(
      Object.entries(changes).map(([key, value]) => [
        key,
        typeof value === "boolean" ? Number(value) : value,
      ]),
    );
    const optimistic = {
      ...payload,
      clips: payload.clips.map((clip) => selectedClipIds.includes(clip.id)
        ? { ...clip, ...normalized } as ArrangementClip
        : clip),
    };
    if (Object.keys(changes).some((key) => liveClipControlKeys.has(key))) {
      payloadRef.current = optimistic;
      setPayload(optimistic);
      syncLiveAudio(optimistic);
    }
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("batch_update_arrangement_clips", { clipIds: selectedClipIds, changes }));
      } else {
        applyPayload({
          ...payload,
          clips: payload.clips.map((clip) => selectedClipIds.includes(clip.id)
            ? { ...clip, ...Object.fromEntries(Object.entries(changes).map(([key, value]) => [key, typeof value === "boolean" ? Number(value) : value])) }
            : clip),
          selected_clip_ids: selectedClipIds,
        });
      }
    } catch (reason) {
      if (Object.keys(changes).some((key) => liveClipControlKeys.has(key))) {
        payloadRef.current = payload;
        setPayload(payload);
        syncLiveAudio(payload);
      }
      setError(String(reason));
    }
  }

  async function shiftSelectedGroup(delta: -1 | 1) {
    if (!payload || selectedClip?.group_id == null) return;
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("shift_arrangement_group_channels", {
          projectId: payload.project.id, groupId: selectedClip.group_id, delta,
        }));
      } else {
        const groupId = selectedClip.group_id;
        const members = payload.clips.filter((clip) => clip.group_id === groupId);
        if (members.some((clip) => clip.channel + delta < 1 || clip.channel + delta > 4)) throw new Error("The group cannot move beyond channels 1 to 4.");
        applyPayload({ ...payload, clips: payload.clips.map((clip) => clip.group_id === groupId ? { ...clip, channel: clip.channel + delta } : clip), selected_clip_ids: members.map((clip) => clip.id) });
      }
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function deleteSelectedClips() {
    if (!payload || selectedClipIds.length === 0 || selectedClips.some((clip) => clip.locked)) return;
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("delete_arrangement_clips", { clipIds: selectedClipIds }));
      } else {
        applyPayload({ ...payload, clips: payload.clips.filter((clip) => !selectedClipIds.includes(clip.id)) });
      }
      setSelectedClipIds([]);
      setSelectedClipId(null);
      pauseTimelineAudition();
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function trimSelectedToSelection() {
    if (!payload || !hasSelection || selectionStart == null || selectionEnd == null || selectedClipIds.length === 0) return;
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("trim_arrangement_clips_to_selection", {
          clipIds: selectedClipIds, startSeconds: selectionStart, endSeconds: selectionEnd,
        }));
      } else {
        const selected = payload.clips.filter((clip) => selectedClipIds.includes(clip.id));
        if (selected.some((clip) => Math.max(selectionStart, clip.start_seconds) >= Math.min(selectionEnd, clip.start_seconds + clip.duration_seconds))) {
          throw new Error("Every selected clip must overlap the timeline selection.");
        }
        applyPayload({
          ...payload,
          clips: payload.clips.map((clip) => {
            if (!selectedClipIds.includes(clip.id)) return clip;
            const oldEnd = clip.start_seconds + clip.duration_seconds;
            const start = Math.max(selectionStart, clip.start_seconds);
            const end = Math.min(selectionEnd, oldEnd);
            const trimLeft = start - clip.start_seconds;
            const trimRight = oldEnd - end;
            return {
              ...clip,
              start_seconds: start,
              duration_seconds: end - start,
              source_in_seconds: clip.source_in_seconds
                + (clip.reversed ? trimRight : trimLeft) * tempoFactor(clip),
            };
          }),
          selected_clip_ids: selectedClipIds,
        });
      }
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function refreshStemStatus() {
    if (!payload || !isDesktop()) return;
    const trackIds = Array.from(new Set(payload.clips.map((clip) => clip.track_id)));
    setStemStatus(await invoke<StemStatusPayload>("load_stem_status", { trackIds }));
  }

  async function separateSelectedTrackStems(force = false) {
    if (!selectedClip || !stemStatus?.capability.available || selectedStemBusy) return;
    const trackId = selectedClip.track_id;
    setSeparatingTrackId(trackId);
    setStemProgress({
      track_id: trackId,
      status: "queued",
      phase: "queued",
      progress: 0,
      stem_count: 0,
      cached: false,
      error: "",
    });
    setError(null);
    try {
      if (!selectedClip.expanded) await updateClip(selectedClip.id, { expanded: true });
      await invoke("separate_track_stems", { trackId, force });
      await refreshStemStatus();
    } catch (reason) {
      setError(String(reason));
      try {
        await refreshStemStatus();
      } catch {
        // Keep the separation error as the useful failure message.
      }
    } finally {
      setSeparatingTrackId(null);
    }
  }

  function previewStem(asset: StemAsset) {
    pauseTimelineAudition();
    const togglingOff = previewingStemKind === asset.stem_kind;
    stopStemPreview();
    if (togglingOff) return;
    const audio = new Audio(convertFileSrc(asset.path));
    stemPreviewAudioRef.current = audio;
    setPreviewingStemKind(asset.stem_kind);
    audio.onended = () => {
      if (stemPreviewAudioRef.current === audio) stemPreviewAudioRef.current = null;
      setPreviewingStemKind((kind) => kind === asset.stem_kind ? null : kind);
    };
    audio.onerror = () => {
      if (stemPreviewAudioRef.current === audio) stemPreviewAudioRef.current = null;
      setPreviewingStemKind(null);
      setError(`Could not play the ${asset.stem_kind} stem.`);
    };
    void audio.play().catch((reason) => {
      if (stemPreviewAudioRef.current === audio) stemPreviewAudioRef.current = null;
      setPreviewingStemKind(null);
      setError(`Could not play the ${asset.stem_kind} stem: ${String(reason)}`);
    });
  }

  async function setSelectedClipSource(clipKind: "song" | StemKind) {
    if (!payload || !selectedClip || selectedClip.locked || selectedClip.clip_kind === clipKind) return;
    stopStemPreview();
    pauseTimelineAudition();
    setBusy(true);
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("set_arrangement_clip_source", {
          clipId: selectedClip.id,
          clipKind,
        }));
      } else {
        applyPayload({
          ...payload,
          clips: payload.clips.map((clip) => clip.id === selectedClip.id ? { ...clip, clip_kind: clipKind } : clip),
          selected_clip_id: selectedClip.id,
        });
      }
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    } finally {
      setBusy(false);
    }
  }

  async function addSelectedStemToArrangement(stemKind: StemKind) {
    if (!payload || !selectedClip || !selectedStemsReady) return;
    stopStemPreview();
    setBusy(true);
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("add_stem_to_arrangement", {
          sourceClipId: selectedClip.id,
          stemKind,
          channel: stemTargetChannel,
        }));
      } else {
        throw new Error("Editable stems are available in the desktop app.");
      }
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    } finally {
      setBusy(false);
    }
  }

  async function consolidateSelectedClip(mode: "freeze" | "unfreeze" | "bounce") {
    if (!payload || !selectedClip || !isDesktop() || busy) return;
    setBusy(true);
    setStatus(mode === "bounce" ? "Bouncing clip" : mode === "freeze" ? "Freezing clip" : "Unfreezing clip");
    setError(null);
    try {
      const command = mode === "bounce"
        ? "bounce_arrangement_clip"
        : mode === "freeze"
          ? "freeze_arrangement_clip"
          : "unfreeze_arrangement_clip";
      applyPayload(await invoke<ArrangementPayload>(command, { clipId: selectedClip.id }));
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    } finally {
      setBusy(false);
    }
  }

  async function revealConsolidatedSource() {
    if (!isDesktop() || !selectedClip?.path || !selectedClip.rendered_mode) return;
    try {
      await invoke("reveal_consolidated_audio", { path: selectedClip.path });
      setStatus("Audio revealed in Finder");
    } catch (error) {
      setStatus(String(error));
    }
  }

  function matchSelectedClipKey() {
    if (!selectedClip || !keyMatchTarget || !selectedKeyMatch || selectedClip.locked) return;
    void updateClip(selectedClip.id, { pitch_semitones: selectedKeyMatch.pitchSemitones });
  }

  async function cancelSelectedStemSeparation() {
    if (!selectedStemBusy || !isDesktop()) return;
    try {
      await invoke<boolean>("cancel_stem_separation");
      setStemProgress((current) => current ? { ...current, phase: "cancelling" } : current);
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function refreshRenderStatus() {
    if (!payload || !isDesktop()) return;
    const clipIds = payload.clips.map((clip) => clip.id);
    setRenderStatus(await invoke<RenderStatusPayload>("load_render_status", { clipIds }));
  }

  async function renderClipPreview(clip: ArrangementClip, force = false) {
    if (!renderStatus?.capability.available || renderingClipId != null || !isDesktop()) return;
    setRenderingClipId(clip.id);
    setRenderProgress({
      clip_id: clip.id,
      status: "queued",
      phase: "queued",
      progress: 0,
      cached: false,
      path: "",
      error: "",
    });
    setError(null);
    try {
      await invoke("render_arrangement_clip", { clipId: clip.id, force });
      await refreshRenderStatus();
    } catch (reason) {
      setError(String(reason));
      try {
        await refreshRenderStatus();
      } catch {
        // Preserve the render error shown to the user.
      }
    } finally {
      setRenderingClipId(null);
    }
  }

  async function cancelActiveRender() {
    if (renderingClipId == null || !isDesktop()) return;
    try {
      await invoke<boolean>("cancel_clip_render");
      setRenderProgress((current) => current ? { ...current, phase: "cancelling" } : current);
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function addTrack(track: ArrangementLibraryTrack, channel = targetChannel, startSeconds: number | null = null) {
    if (!payload || track.missing) return;
    setBusy(true);
    setStatus("Saving");
    try {
      if (isDesktop()) {
        const next = await invoke<ArrangementPayload>("add_track_to_arrangement", {
          projectId: payload.project.id,
          trackId: track.id,
          channel,
          startSeconds,
        });
        applyPayload(next);
        await refreshProjectList();
      } else {
        const channelClips = payload.clips.filter((clip) => clip.channel === channel);
        const start = startSeconds ?? Math.max(0, ...channelClips.map((clip) => clip.start_seconds + clip.duration_seconds));
        const nextId = Math.max(0, ...payload.clips.map((clip) => clip.id)) + 1;
        const nextClip: ArrangementClip = {
          id: nextId, project_id: payload.project.id, track_id: track.id,
          clip_kind: "song",
          title: track.title, artist: track.artist, path: track.path ?? "",
          source_bpm: track.bpm, source_key: track.key, channel,
          source_duration_seconds: durationToSeconds(track.duration),
          start_seconds: start, source_in_seconds: 0, duration_seconds: durationToSeconds(track.duration),
          gain_db: 0, pan: 0, pitch_semitones: 0, tempo_percent: 100,
          color: channelColors[channel - 1], expanded: 0, locked: 0, muted: 0, solo: 0,
          loop_enabled: 0, reversed: 0, fade_in_seconds: 0, fade_out_seconds: 0,
          eq_low_db: 0, eq_mid_db: 0, eq_high_db: 0, highpass_hz: 20, lowpass_hz: 20000,
          compressor_enabled: 0, compressor_threshold_db: -18, compressor_ratio: 4,
          group_id: null,
          stem_states: {},
        };
        applyPayload({ ...payload, clips: [...payload.clips, nextClip], selected_clip_id: nextId });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    } finally {
      setBusy(false);
    }
  }

  async function updateClip(clipId: number, changes: Record<string, string | number | boolean>) {
    if (!payload) return;
    const normalizedChanges = Object.fromEntries(
      Object.entries(changes).map(([key, value]) => [
        key,
        typeof value === "boolean" ? Number(value) : value,
      ]),
    );
    const optimistic = {
      ...payload,
      clips: payload.clips.map((clip) => clip.id === clipId
        ? { ...clip, ...normalizedChanges } as ArrangementClip
        : clip),
    };
    if (Object.keys(changes).some((key) => liveClipControlKeys.has(key))) {
      payloadRef.current = optimistic;
      setPayload(optimistic);
      syncLiveAudio(optimistic);
    }
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("update_arrangement_clip", { clipId, changes }));
      } else {
        const target = payload.clips.find((clip) => clip.id === clipId);
        const groupDelta = target?.group_id != null && typeof changes.start_seconds === "number"
          ? changes.start_seconds - target.start_seconds
          : null;
        applyPayload({
          ...payload,
          clips: payload.clips.map((clip) => {
            if (clip.id === clipId) return {
              ...clip,
              ...Object.fromEntries(Object.entries(changes).map(([key, value]) => [key, typeof value === "boolean" ? Number(value) : value])),
            };
            return groupDelta != null && clip.group_id === target?.group_id
              ? { ...clip, start_seconds: Math.max(0, clip.start_seconds + groupDelta) }
              : clip;
          }),
        });
      }
    } catch (reason) {
      if (Object.keys(changes).some((key) => liveClipControlKeys.has(key))) {
        payloadRef.current = payload;
        setPayload(payload);
        syncLiveAudio(payload);
      }
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function updateStemLaneState(
    clipId: number,
    stemKind: StemKind,
    changes: { muted?: boolean; solo?: boolean },
  ) {
    if (!payload) return;
    stopStemPreview();
    pauseTimelineAudition();
    setStatus("Saving stem mix");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("update_arrangement_stem_state", {
          clipId,
          stemKind,
          ...changes,
        }));
      } else {
        applyPayload({
          ...payload,
          clips: payload.clips.map((clip) => {
            if (clip.id !== clipId) return clip;
            const current = stemLaneState(clip, stemKind);
            const next = {
              muted: changes.muted == null ? current.muted : Number(changes.muted),
              solo: changes.solo == null ? current.solo : Number(changes.solo),
            };
            if (changes.muted) next.solo = 0;
            if (changes.solo) next.muted = 0;
            return {
              ...clip,
              stem_states: { ...clip.stem_states, [stemKind]: next },
            };
          }),
          selected_clip_id: clipId,
        });
      }
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Stem mix not saved");
    }
  }

  async function resizeClip(
    clipId: number,
    edge: ClipResizeEdge,
    boundarySeconds: number,
    originalPayload: ArrangementPayload,
  ) {
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("resize_arrangement_clip", {
          clipId,
          edge,
          boundarySeconds,
        }));
        await refreshProjectList();
      } else {
        const target = originalPayload.clips.find((clip) => clip.id === clipId);
        if (!target) throw new Error("Timeline clip was not found.");
        applyPayload({
          ...originalPayload,
          clips: originalPayload.clips.map((clip) => (
            clip.id === clipId ? resizedClipAtBoundary(target, edge, boundarySeconds) : clip
          )),
          selected_clip_id: clipId,
        });
      }
    } catch (reason) {
      setPayload(originalPayload);
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function retimeClip(
    clipId: number,
    tempoPercent: number,
    originalPayload: ArrangementPayload,
  ) {
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("update_arrangement_clip", {
          clipId,
          changes: { tempo_percent: tempoPercent },
        }));
        await refreshProjectList();
      } else {
        const target = originalPayload.clips.find((clip) => clip.id === clipId);
        if (!target) throw new Error("Timeline clip was not found.");
        applyPayload({
          ...originalPayload,
          clips: originalPayload.clips.map((clip) => (
            clip.id === clipId ? retimedClipAtTempo(target, tempoPercent) : clip
          )),
          selected_clip_id: clipId,
        });
      }
    } catch (reason) {
      setPayload(originalPayload);
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  function beginClipMove(
    event: ReactPointerEvent<HTMLButtonElement>,
    clip: ArrangementClip,
  ) {
    if (!payload || clip.locked || event.button !== 0) return;
    event.stopPropagation();
    draggedClip.current = null;
    draggedTrack.current = null;
    setSelectedClipId(clip.id);
    setSelectedClipIds([clip.id]);
    setSelectedMarkerId(null);
    setError(null);

    const originalPayload = payload;
    const initialPointerX = event.clientX;
    const initialPointerY = event.clientY;
    let latestStart = clip.start_seconds;
    let latestChannel = clip.channel;
    let moved = false;

    const previewAt = (startSeconds: number, channel: number): ArrangementPayload => {
      const delta = startSeconds - clip.start_seconds;
      return {
        ...originalPayload,
        clips: originalPayload.clips.map((item) => {
          if (item.id === clip.id) return {
            ...item,
            start_seconds: startSeconds,
            channel,
          };
          return clip.group_id != null && item.group_id === clip.group_id
            ? { ...item, start_seconds: Math.max(0, item.start_seconds + delta) }
            : item;
        }),
        selected_clip_id: clip.id,
        selected_clip_ids: [clip.id],
      };
    };

    const finish = async (cancelled: boolean) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", complete);
      window.removeEventListener("pointercancel", cancel);
      document.body.classList.remove("clip-move-active");
      window.setTimeout(() => { suppressClipClick.current = false; }, 0);
      if (cancelled) {
        setPayload(originalPayload);
        setStatus("Saved");
        return;
      }
      if (!moved) return;
      setStatus("Saving");
      try {
        if (isDesktop()) {
          applyPayload(await invoke<ArrangementPayload>("update_arrangement_clip", {
            clipId: clip.id,
            changes: { start_seconds: latestStart, channel: latestChannel },
          }));
          await refreshProjectList();
        } else {
          applyPayload(previewAt(latestStart, latestChannel));
        }
      } catch (reason) {
        setPayload(originalPayload);
        setError(String(reason));
        setStatus("Not saved");
      }
    };
    const move = (moveEvent: PointerEvent) => {
      const distance = Math.hypot(
        moveEvent.clientX - initialPointerX,
        moveEvent.clientY - initialPointerY,
      );
      if (!moved && distance < 6) return;
      moveEvent.preventDefault();
      if (!moved) pauseTimelineAudition();
      moved = true;
      suppressClipClick.current = true;
      document.body.classList.add("clip-move-active");
      const rawStart = clip.start_seconds + (moveEvent.clientX - initialPointerX) / zoom;
      latestStart = Math.round(
        (moveEvent.altKey ? Math.max(0, rawStart) : snapTime(rawStart)) * 1000,
      ) / 1000;
      const lane = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY)
        ?.closest<HTMLElement>(".song-lane[data-channel]");
      const hoveredChannel = Number(lane?.dataset.channel);
      latestChannel = Number.isInteger(hoveredChannel)
        && hoveredChannel >= 1
        && hoveredChannel <= 4
        ? hoveredChannel
        : latestChannel;
      setPayload(previewAt(latestStart, latestChannel));
      setStatus("Unsaved");
    };
    const complete = () => { void finish(false); };
    const cancel = () => { void finish(true); };

    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", complete, { once: true });
    window.addEventListener("pointercancel", cancel, { once: true });
  }

  function beginClipResize(
    event: ReactPointerEvent<HTMLSpanElement>,
    clip: ArrangementClip,
    edge: ClipResizeEdge,
  ) {
    if (!payload || clip.locked) return;
    event.preventDefault();
    event.stopPropagation();
    pauseTimelineAudition();
    draggedClip.current = null;
    draggedTrack.current = null;
    suppressClipClick.current = true;
    setSelectedClipId(clip.id);
    setSelectedClipIds([clip.id]);
    setSelectedMarkerId(null);
    setError(null);

    const originalPayload = payload;
    const initialPointerX = event.clientX;
    const initialBoundary = edge === "start"
      ? clip.start_seconds
      : clip.start_seconds + clip.duration_seconds;
    let latestBoundary = initialBoundary;
    let latestTempoPercent = clip.tempo_percent;
    let retiming = false;
    let moved = false;

    const finish = (cancelled: boolean) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", complete);
      window.removeEventListener("pointercancel", cancel);
      document.body.classList.remove("clip-resize-active");
      window.setTimeout(() => { suppressClipClick.current = false; }, 0);
      if (cancelled) {
        setPayload(originalPayload);
        setStatus("Saved");
      } else if (moved) {
        if (retiming) {
          void retimeClip(clip.id, latestTempoPercent, originalPayload);
        } else {
          void resizeClip(clip.id, edge, latestBoundary, originalPayload);
        }
      } else {
        setStatus("Saved");
      }
    };
    const move = (moveEvent: PointerEvent) => {
      const rawBoundary = initialBoundary + (moveEvent.clientX - initialPointerX) / zoom;
      const requested = moveEvent.altKey ? Math.max(0, rawBoundary) : snapTime(rawBoundary);
      retiming = edge === "end" && moveEvent.shiftKey;
      const preview = retiming
        ? retimedClipAtEndBoundary(clip, requested)
        : resizedClipAtBoundary(clip, edge, requested);
      latestBoundary = edge === "start"
        ? preview.start_seconds
        : preview.start_seconds + preview.duration_seconds;
      latestTempoPercent = preview.tempo_percent;
      moved = moved || Math.abs(latestBoundary - initialBoundary) >= 0.001;
      setPayload((current) => current ? {
        ...current,
        clips: current.clips.map((item) => item.id === clip.id ? preview : item),
      } : current);
      setStatus("Unsaved");
    };
    const complete = () => finish(false);
    const cancel = () => finish(true);

    document.body.classList.add("clip-resize-active");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", complete, { once: true });
    window.addEventListener("pointercancel", cancel, { once: true });
  }

  function stageClip(clipId: number, changes: Partial<ArrangementClip>) {
    if (!payload) return;
    const next = {
      ...payload,
      clips: payload.clips.map((clip) => clip.id === clipId ? { ...clip, ...changes } : clip),
    };
    payloadRef.current = next;
    setPayload(next);
    syncLiveAudio(next);
    setStatus("Unsaved");
  }

  function stageMaster(changes: Partial<ArrangementProject>) {
    if (!payload) return;
    const next = { ...payload, project: { ...payload.project, ...changes } };
    payloadRef.current = next;
    setPayload(next);
    syncLiveAudio(next);
    setStatus("Unsaved");
  }

  function stageSelectedClips(changes: Partial<ArrangementClip>) {
    if (!payload || selectedClipIds.length === 0) return;
    const next = {
      ...payload,
      clips: payload.clips.map((clip) => selectedClipIds.includes(clip.id)
        ? { ...clip, ...changes }
        : clip),
    };
    payloadRef.current = next;
    setPayload(next);
    syncLiveAudio(next);
    setStatus("Unsaved");
  }

  function stageClipTargetBpm(clip: ArrangementClip, targetBpm: number) {
    const tempoPercent = tempoPercentForBpm(clip, targetBpm);
    if (tempoPercent == null) return;
    const preview = retimedClipAtTempo(clip, tempoPercent);
    stageClip(clip.id, {
      tempo_percent: preview.tempo_percent,
      duration_seconds: preview.duration_seconds,
    });
  }

  function commitClipTargetBpm(clip: ArrangementClip, targetBpm: number) {
    if (!payload) return;
    const tempoPercent = tempoPercentForBpm(clip, targetBpm);
    if (tempoPercent == null) return;
    const originalPayload = payload;
    const preview = retimedClipAtTempo(clip, tempoPercent);
    setPayload({
      ...payload,
      clips: payload.clips.map((item) => item.id === clip.id ? preview : item),
    });
    void retimeClip(clip.id, tempoPercent, originalPayload);
  }

  async function duplicateClip() {
    if (!payload || !selectedClip) return;
    setBusy(true);
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("duplicate_arrangement_clip", { clipId: selectedClip.id }));
      } else {
        const nextId = Math.max(0, ...payload.clips.map((clip) => clip.id)) + 1;
        const duplicate = {
          ...selectedClip,
          id: nextId,
          start_seconds: selectedClip.start_seconds + selectedClip.duration_seconds,
          locked: 0,
        };
        applyPayload({ ...payload, clips: [...payload.clips, duplicate], selected_clip_id: nextId });
      }
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    } finally {
      setBusy(false);
    }
  }

  async function splitClip() {
    if (!payload || !selectedClip || !canSplitAtPlayhead || splitOffset == null) return;
    const offset = splitOffset;
    setBusy(true);
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("split_arrangement_clip", {
          clipId: selectedClip.id,
          offsetSeconds: offset,
        }));
      } else {
        if (offset < 0.05 || offset > selectedClip.duration_seconds - 0.05) {
          throw new Error("Split point must be inside the clip with room on both sides.");
        }
        const nextId = Math.max(0, ...payload.clips.map((clip) => clip.id)) + 1;
        const remaining = selectedClip.duration_seconds - offset;
        const leftSourceIn = selectedClip.reversed
          ? selectedClip.source_in_seconds + remaining
          : selectedClip.source_in_seconds;
        const rightSourceIn = selectedClip.reversed
          ? selectedClip.source_in_seconds
          : selectedClip.source_in_seconds + offset;
        const left = {
          ...selectedClip,
          source_in_seconds: leftSourceIn,
          duration_seconds: offset,
          loop_enabled: 0,
          fade_in_seconds: Math.min(selectedClip.fade_in_seconds, offset),
          fade_out_seconds: 0,
        };
        const right = {
          ...selectedClip,
          id: nextId,
          start_seconds: selectedClip.start_seconds + offset,
          source_in_seconds: rightSourceIn,
          duration_seconds: remaining,
          locked: 0,
          loop_enabled: 0,
          fade_in_seconds: 0,
          fade_out_seconds: Math.min(selectedClip.fade_out_seconds, remaining),
        };
        applyPayload({
          ...payload,
          clips: [...payload.clips.map((clip) => clip.id === selectedClip.id ? left : clip), right],
          selected_clip_id: nextId,
        });
      }
      await refreshProjectList();
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    } finally {
      setBusy(false);
    }
  }

  async function quantizeClip() {
    if (!payload || !selectedClip) return;
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("quantize_arrangement_clip", { clipId: selectedClip.id }));
      } else {
        applyPayload({
          ...payload,
          clips: payload.clips.map((clip) => clip.id === selectedClip.id
            ? { ...clip, start_seconds: snapTime(clip.start_seconds) }
            : clip),
          selected_clip_id: selectedClip.id,
        });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function crossfadeClip() {
    if (!payload || !selectedClip || !crossfadeTargetId) return;
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("crossfade_arrangement_clips", {
          clipId: selectedClip.id,
          targetClipId: crossfadeTargetId,
        }));
      } else {
        const target = payload.clips.find((clip) => clip.id === crossfadeTargetId);
        if (!target) throw new Error("Crossfade target was not found.");
        const [outgoing, incoming] = [selectedClip, target]
          .sort((left, right) => left.start_seconds - right.start_seconds);
        const overlap = outgoing.start_seconds + outgoing.duration_seconds - incoming.start_seconds;
        if (overlap <= 0) throw new Error("Crossfade clips must overlap on the timeline.");
        const duration = Math.min(
          overlap,
          outgoing.duration_seconds - outgoing.fade_in_seconds,
          incoming.duration_seconds - incoming.fade_out_seconds,
        );
        applyPayload({
          ...payload,
          clips: payload.clips.map((clip) => clip.id === outgoing.id
            ? { ...clip, fade_out_seconds: duration }
            : clip.id === incoming.id ? { ...clip, fade_in_seconds: duration } : clip),
          selected_clip_id: selectedClip.id,
        });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function createMarker(markerKind: "marker" | "section") {
    if (!payload) return;
    const kindCount = payload.markers.filter((marker) => marker.marker_kind === markerKind).length + 1;
    const start = snapTime(timelinePosition);
    const sectionLength = (60 / payload.project.tempo) * 32;
    const marker: ProjectMarker = {
      id: Math.max(0, ...payload.markers.map((item) => item.id)) + 1,
      project_id: payload.project.id,
      marker_kind: markerKind,
      name: markerKind === "marker" ? `Marker ${kindCount}` : `Section ${kindCount}`,
      start_seconds: start,
      end_seconds: markerKind === "section" ? start + sectionLength : null,
      color: markerKind === "marker" ? "violet" : "cyan",
    };
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("create_arrangement_marker", {
          projectId: payload.project.id,
          markerKind: marker.marker_kind,
          name: marker.name,
          startSeconds: marker.start_seconds,
          endSeconds: marker.end_seconds,
          color: marker.color,
        }));
      } else {
        applyPayload({ ...payload, markers: [...payload.markers, marker], selected_marker_id: marker.id });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  function navigateMarker(direction: -1 | 1) {
    if (!payload || payload.markers.length === 0) return;
    const ordered = [...payload.markers].sort((left, right) => left.start_seconds - right.start_seconds);
    const next = direction < 0
      ? [...ordered].reverse().find((marker) => marker.start_seconds < timelinePosition - 0.001) ?? ordered[ordered.length - 1]
      : ordered.find((marker) => marker.start_seconds > timelinePosition + 0.001) ?? ordered[0];
    const wasPlaying = previewing || auditionStarting.current;
    pauseTimelineAudition();
    setSelectedMarkerId(next.id);
    setSelectedClipId(null);
    setTimelinePosition(next.start_seconds);
    if (wasPlaying) void startTimelineAudition(next.start_seconds);
  }

  function stageMarker(markerId: number, changes: Partial<ProjectMarker>) {
    if (!payload) return;
    setPayload({
      ...payload,
      markers: payload.markers.map((marker) => marker.id === markerId ? { ...marker, ...changes } : marker),
    });
    setStatus("Unsaved");
  }

  async function updateMarker(markerId: number, changes: Record<string, string | number | null>) {
    if (!payload) return;
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("update_arrangement_marker", { markerId, changes }));
      } else {
        applyPayload({
          ...payload,
          markers: payload.markers.map((marker) => marker.id === markerId ? { ...marker, ...changes } as ProjectMarker : marker),
          selected_marker_id: markerId,
        });
      }
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  async function deleteMarker() {
    if (!payload || !selectedMarker) return;
    setStatus("Saving");
    try {
      if (isDesktop()) {
        applyPayload(await invoke<ArrangementPayload>("delete_arrangement_marker", { markerId: selectedMarker.id }));
      } else {
        applyPayload({ ...payload, markers: payload.markers.filter((marker) => marker.id !== selectedMarker.id) });
      }
      setSelectedMarkerId(null);
      setSelectedClipId(payload.clips[0]?.id ?? null);
    } catch (reason) {
      setError(String(reason));
      setStatus("Not saved");
    }
  }

  function placeTimelinePosition(event: React.MouseEvent<HTMLElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const next = snapTime((event.clientX - bounds.left) / zoom);
    const wasPlaying = previewing || auditionStarting.current;
    pauseTimelineAudition();
    setTimelinePosition(next);
    if (wasPlaying) void startTimelineAudition(next);
  }

  async function dropOnChannel(channel: number, event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const lane = event.currentTarget.getBoundingClientRect();
    const start = snapTime(Math.max(0, (event.clientX - lane.left) / zoom));
    const roundedStart = Math.round(start * 1000) / 1000;
    const stem = draggedStem.current;
    if (stem != null) {
      draggedStem.current = null;
      setBusy(true);
      setStatus("Adding stem clip");
      try {
        if (!isDesktop()) throw new Error("Editable stems are available in the desktop app.");
        applyPayload(await invoke<ArrangementPayload>("add_stem_to_arrangement", {
          sourceClipId: stem.sourceClipId,
          stemKind: stem.stemKind,
          channel,
          startSeconds: roundedStart,
        }));
        await refreshProjectList();
      } catch (reason) {
        setError(String(reason));
        setStatus("Not saved");
      } finally {
        setBusy(false);
      }
      return;
    }
    const trackId = draggedTrack.current;
    if (trackId != null) {
      const track = tracks.find((item) => item.id === trackId);
      if (track) await addTrack(track, channel, roundedStart);
      draggedTrack.current = null;
      return;
    }
    const clipId = draggedClip.current;
    if (clipId == null) return;
    await updateClip(clipId, { channel, start_seconds: roundedStart });
    draggedClip.current = null;
  }

  useEffect(() => {
    const handleTimelineShortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, select, textarea, [contenteditable='true']") || event.repeat) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        void (event.shiftKey ? redoProject() : undoProject());
      } else if ((event.key === "Backspace" || event.key === "Delete") && selectedClipIds.length > 0) {
        event.preventDefault();
        void deleteSelectedClips();
      } else if (event.code === "Space") {
        event.preventDefault();
        toggleTimelineAudition();
      } else if (event.key.toLowerCase() === "s" && canSplitAtPlayhead) {
        event.preventDefault();
        void splitClip();
      } else if (event.key.toLowerCase() === "m") {
        event.preventDefault();
        void createMarker(event.shiftKey ? "section" : "marker");
      } else if (event.key.toLowerCase() === "i") {
        event.preventDefault();
        setSelectionBoundary("start");
      } else if (event.key.toLowerCase() === "o") {
        event.preventDefault();
        setSelectionBoundary("end");
      } else if (event.key.toLowerCase() === "l") {
        event.preventDefault();
        toggleSelectionLoop();
      } else if (event.key === "[") {
        event.preventDefault();
        navigateMarker(-1);
      } else if (event.key === "]") {
        event.preventDefault();
        navigateMarker(1);
      }
    };
    window.addEventListener("keydown", handleTimelineShortcut);
    return () => window.removeEventListener("keydown", handleTimelineShortcut);
  }, [payload, selectedClipId, timelinePosition, previewing, canSplitAtPlayhead, hasSelection]);

  if (!payload) {
    return (
      <section className="arrangement-empty">
        <Waveform size={34} />
        <h1>Start an arrangement</h1>
        <p>Create a non-destructive four-channel project. Original music remains untouched.</p>
        <button disabled={busy} onClick={createProject}><Plus size={16} /> {busy ? "Creating..." : "New project"}</button>
        {error && <small>{error}</small>}
      </section>
    );
  }

  return (
    <>
      <section className="arrangement-shell">
        <aside className="arrangement-library">
          <div className="arrangement-pane-title"><MusicNotes size={16} /><div><strong>Source library</strong><span>{tracks.length} indexed tracks</span></div></div>
          <label className="arrangement-search"><MagnifyingGlass size={14} /><input aria-label="Search arrangement source library" value={libraryQuery} onChange={(event) => setLibraryQuery(event.target.value)} placeholder="Search title, artist, BPM or key" /></label>
          <div className="channel-target" aria-label="Target arrangement channel">
            <span>Add to</span>
            {[1, 2, 3, 4].map((channel) => <button aria-label={`Target channel ${channel}`} key={channel} className={targetChannel === channel ? "active" : ""} onClick={() => setTargetChannel(channel)}>{channel}</button>)}
          </div>
          <div className="arrangement-track-list">
            {filteredTracks.slice(0, 80).map((track) => (
              <div
                className={track.missing ? "arrangement-source missing" : "arrangement-source"}
                key={track.id}
                draggable={!track.missing}
                onDragStart={(event) => { draggedTrack.current = track.id; draggedClip.current = null; event.dataTransfer.effectAllowed = "copy"; }}
                onDragEnd={() => { draggedTrack.current = null; }}
                title={track.missing ? "Source file is missing" : "Drag onto a channel or use the add button"}
              >
                <span className={`source-color ${track.color || "violet"}`} />
                <div><strong>{track.title}</strong><span>{track.artist || "Unknown artist"}</span><small>{track.bpm || "--"} BPM&nbsp;&nbsp; {track.key || "--"}&nbsp;&nbsp; {track.duration}</small></div>
                <button disabled={busy || track.missing} onClick={() => addTrack(track)} aria-label={`Add ${track.title} to channel ${targetChannel}`}><Plus size={14} /></button>
              </div>
            ))}
            {filteredTracks.length === 0 && <p className="arrangement-list-empty">No matching library tracks.</p>}
          </div>
        </aside>

        <section className="arrangement-centre">
          <header className="arrangement-header">
            <div className="project-picker">
              <select value={payload.project.id} onChange={(event) => openProject(Number(event.target.value))} aria-label="Open project">
                {!projects.some((project) => project.id === payload.project.id) && <option value={payload.project.id}>{payload.project.name}</option>}
                {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
              </select>
              <button onClick={createProject} aria-label="Create project"><Plus size={15} /></button>
            </div>
            <input className="project-name" value={payload.project.name} onChange={(event) => { setPayload({ ...payload, project: { ...payload.project, name: event.target.value } }); setStatus("Unsaved"); }} onBlur={(event) => saveProjectDetails(event.target.value, payload.project.tempo)} aria-label="Project name" />
            <label className="project-tempo"><span>BPM</span><input type="number" min="40" max="240" step="0.1" value={payload.project.tempo} onChange={(event) => { setPayload({ ...payload, project: { ...payload.project, tempo: Number(event.target.value) } }); setStatus("Unsaved"); }} onBlur={(event) => saveProjectDetails(payload.project.name, Number(event.target.value))} /></label>
            <div className="history-actions"><button aria-label="Undo project edit" title="Undo Command+Z" disabled={!payload.can_undo} onClick={undoProject}><ArrowCounterClockwise size={13} /></button><button aria-label="Redo project edit" title="Redo Shift+Command+Z" disabled={!payload.can_redo} onClick={redoProject}><ArrowClockwise size={13} /></button></div>
            <span className={`save-state ${status === "Not saved" ? "error" : status === "Unsaved" ? "pending" : ""}`}><FloppyDisk size={13} /> {status}</span>
          </header>

          <div className="timeline-toolbar">
            <button
              className={payload.project.snap_enabled ? "active" : ""}
              aria-pressed={Boolean(payload.project.snap_enabled)}
              onClick={() => updateSnapSettings({ snap_enabled: payload.project.snap_enabled ? 0 : 1 })}
            ><Magnet size={13} weight={payload.project.snap_enabled ? "fill" : "regular"} /> Snap</button>
            <label><span>Grid</span><select aria-label="Snap grid" value={payload.project.snap_beats} onChange={(event) => updateSnapSettings({ snap_beats: Number(event.target.value) })}>
              <option value={4}>Bar</option>
              <option value={2}>2 beats</option>
              <option value={1}>Beat</option>
              <option value={0.5}>1/2 beat</option>
              <option value={0.25}>1/4 beat</option>
              <option value={0.125}>1/8 beat</option>
            </select></label>
            <button disabled={!selectedClip || Boolean(selectedClip.locked)} onClick={quantizeClip}><Magnet size={13} /> Quantize clip</button>
            <button title="Set selection start I" onClick={() => setSelectionBoundary("start")}>In</button>
            <button title="Set selection end O" onClick={() => setSelectionBoundary("end")}>Out</button>
            <button className={payload.project.selection_loop_enabled ? "active" : ""} aria-pressed={Boolean(payload.project.selection_loop_enabled)} title="Toggle selection loop L" onClick={toggleSelectionLoop}><Repeat size={13} /> Loop</button>
            <button disabled={!hasSelection} title="Clear selection" aria-label="Clear timeline selection" onClick={() => updateSelection(null, null, false)}><Trash size={12} /></button>
            <i />
            <button aria-label="Previous cue" title="Previous cue [" disabled={payload.markers.length === 0} onClick={() => navigateMarker(-1)}><CaretLeft size={13} /></button>
            <button aria-label="Next cue" title="Next cue ]" disabled={payload.markers.length === 0} onClick={() => navigateMarker(1)}><CaretRight size={13} /></button>
            <button title="Add marker M" onClick={() => createMarker("marker")}><MapPin size={13} /> Marker</button>
            <button title="Add section Shift+M" onClick={() => createMarker("section")}><Flag size={13} /> Section</button>
            <small>{formatTime(timelinePosition)} <span>/</span> {payload.markers.length} cue{payload.markers.length === 1 ? "" : "s"}</small>
          </div>

          {error && <div className="arrangement-error"><span>{error}</span><button onClick={() => setError(null)}>Dismiss</button></div>}
          <div className="timeline-scroll" ref={timelineScrollRef} title="Pinch, Command-scroll or Option-scroll to zoom">
            <div className="timeline-canvas" style={{
              width: timelineWidth + 112,
              "--lane-height": "120px",
              "--beat-width": `${zoom * (60 / payload.project.tempo)}px`,
              "--bar-width": `${zoom * (60 / payload.project.tempo) * payload.project.time_signature_numerator}px`,
              "--grid-width": `${zoom * (60 / payload.project.tempo) * payload.project.snap_beats}px`,
            } as CSSProperties}>
              <div className="timeline-ruler" style={{ width: timelineWidth, marginLeft: 112 }} onClick={placeTimelinePosition}>
                {rulerTicks.map((tick) => <span key={tick} style={{ left: tick * zoom }}><i />{formatTime(tick)}</span>)}
              </div>
              {hasSelection && <div className={`timeline-selection-region ${payload.project.selection_loop_enabled ? "looping" : ""}`} style={{ left: 112 + selectionStart! * zoom, width: Math.max(2, (selectionEnd! - selectionStart!) * zoom) }}><span>{payload.project.selection_loop_enabled ? "LOOP" : "SELECTION"}</span></div>}
              <div ref={arrangementPlayheadRef} className="arrangement-playhead" style={{ left: 112 + timelinePosition * zoom }}><i /></div>
              <div className="timeline-marker-layer" style={{ left: 112, width: timelineWidth }}>
                {payload.markers.map((marker) => marker.marker_kind === "section" ? (
                  <button
                    className={`timeline-section ${marker.color} ${selectedMarkerId === marker.id ? "selected" : ""}`}
                    style={{ left: marker.start_seconds * zoom, width: Math.max(42, ((marker.end_seconds ?? marker.start_seconds) - marker.start_seconds) * zoom) }}
                    key={marker.id}
                    onClick={(event) => { event.stopPropagation(); setSelectedMarkerId(marker.id); setSelectedClipId(null); if (!previewing) setTimelinePosition(marker.start_seconds); }}
                  ><Flag size={10} weight="fill" /><span>{marker.name}</span></button>
                ) : (
                  <button
                    className={`timeline-marker ${marker.color} ${selectedMarkerId === marker.id ? "selected" : ""}`}
                    style={{ left: marker.start_seconds * zoom }}
                    key={marker.id}
                    onClick={(event) => { event.stopPropagation(); setSelectedMarkerId(marker.id); setSelectedClipId(null); if (!previewing) setTimelinePosition(marker.start_seconds); }}
                  ><MapPin size={10} weight="fill" /><span>{marker.name}</span></button>
                ))}
              </div>
              {[1, 2, 3, 4].map((channel) => {
                const clips = payload.clips.filter((clip) => clip.channel === channel);
                const expanded = clips.filter((clip) => clip.expanded);
                return (
                  <div className="arrangement-channel" key={channel}>
                    <div className="channel-heading"><span>CH {channel}</span><strong>{clips.length ? `${clips.length} clip${clips.length === 1 ? "" : "s"}` : "Empty"}</strong><div className="channel-meter" title={`Channel ${channel} level`}><i style={{ width: `${Math.max(0, Math.min(100, ((channelMeterDb[channel - 1] + 60) / 60) * 100))}%` }} /></div><small>{channelMeterDb[channel - 1] <= -59.9 ? "−∞" : `${channelMeterDb[channel - 1].toFixed(0)} dB`}</small></div>
                    <div className="song-lane" data-channel={channel} style={{ width: timelineWidth }} onClick={placeTimelinePosition} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={(event) => dropOnChannel(channel, event)}>
                      {clips.map((clip) => (
                        <button
                          className={`timeline-clip ${clip.color} ${selectedClipIds.includes(clip.id) ? "selected" : ""} ${clip.locked ? "locked" : ""} ${clip.muted ? "clip-muted" : ""}`}
                          style={{ left: clip.start_seconds * zoom, width: Math.max(12, clip.duration_seconds * zoom) }}
                          key={clip.id}
                          aria-label={`${clip.title}, channel ${clip.channel}, starts ${formatTime(clip.start_seconds)}${clip.loop_enabled ? ", looped" : ""}${clip.reversed ? ", reversed" : ""}`}
                          title={clip.locked ? "Unlock this clip to move it" : "Drag to move freely. Hold Option to ignore Snap."}
                          onPointerDown={(event) => beginClipMove(event, clip)}
                          onClick={(event) => {
                            if (suppressClipClick.current) {
                              event.preventDefault();
                              event.stopPropagation();
                              return;
                            }
                            event.stopPropagation();
                            const bounds = event.currentTarget.getBoundingClientRect();
                            const position = clip.start_seconds + Math.max(0, (event.clientX - bounds.left) / zoom);
                            const additive = event.metaKey || event.ctrlKey;
                            setSelectedClipIds((ids) => {
                              const next = additive
                                ? ids.includes(clip.id) ? ids.filter((id) => id !== clip.id) : [...ids, clip.id]
                                : [clip.id];
                              setSelectedClipId(next[0] ?? clip.id);
                              return next;
                            });
                            setSelectedMarkerId(null);
                            if (!previewing) setTimelinePosition(snapTime(Math.min(clip.start_seconds + clip.duration_seconds, position)));
                          }}
                        >
                          {!clip.locked && <>
                            <span
                              className="clip-resize-handle clip-resize-start"
                              title="Drag to trim or extend clip start. Hold Option for free movement."
                              aria-hidden="true"
                              onPointerDown={(event) => beginClipResize(event, clip, "start")}
                            />
                            <span
                              className="clip-resize-handle clip-resize-end"
                              title="Drag to trim or extend. Shift-drag outward to slow down or inward to speed up. Hold Option to ignore Snap."
                              aria-hidden="true"
                              onPointerDown={(event) => beginClipResize(event, clip, "end")}
                            />
                          </>}
                          <span className="clip-label"><strong>{clip.title}</strong><small>{clipTargetBpm(clip) != null ? `${clipTargetBpm(clip)!.toFixed(2)} BPM` : "BPM unknown"}</small></span>
                          <span className="clip-flags">{clip.clip_kind !== "song" && <i>{clip.rendered_mode?.toUpperCase() ?? clip.clip_kind.toUpperCase()}</i>}{Boolean(clip.loop_enabled) && <i>LOOP</i>}{Boolean(clip.reversed) && <i>REV</i>}</span>
                          {clip.group_id != null && <span className="clip-group-badge">G{clip.group_id}</span>}
                          {clip.fade_in_seconds > 0 && <span className="clip-fade clip-fade-in" style={{ width: Math.min(100, (clip.fade_in_seconds / clip.duration_seconds) * 100) + "%" }} />}
                          {clip.fade_out_seconds > 0 && <span className="clip-fade clip-fade-out" style={{ width: Math.min(100, (clip.fade_out_seconds / clip.duration_seconds) * 100) + "%" }} />}
                          <ClipWaveform clip={clip} zoom={zoom} source={clip.clip_kind === "song" ? waveformSources[clip.track_id] : null} preparedSource={preparedWaveformSources[clip.id]} masterGainDb={payload.project.master_gain_db} />
                          {Boolean(clip.locked) && <Lock size={11} weight="fill" />}
                        </button>
                      ))}
                      {clips.length === 0 && <span className="lane-hint">Drop a clip here</span>}
                    </div>
                    {expanded.length > 0 && <div className="stem-lanes" style={{ width: timelineWidth }}>
                      {stemDefinitions.map((stem, stemIndex) => <div className="stem-lane" key={stem.kind}><span>{stem.label}</span>{expanded.map((clip) => {
                        const ready = stemStatus?.stems.some((asset) => asset.track_id === clip.track_id && asset.stem_kind === stem.kind);
                        const processing = separatingTrackId === clip.track_id;
                        const laneState = stemLaneState(clip, stem.kind);
                        const laneAudible = audibleStemKinds(clip).includes(stem.kind);
                        return <div
                          className={`stem-region ${clip.color} ${ready ? "ready" : processing ? "processing" : "pending"} ${laneState.muted ? "muted" : ""} ${laneState.solo ? "solo" : ""} ${ready && !laneAudible ? "inaudible" : ""}`}
                          style={{ left: clip.start_seconds * zoom, width: Math.max(82, clip.duration_seconds * zoom) }}
                          title={`${stem.label}: ${laneState.solo ? "soloed" : laneState.muted ? "muted" : ready ? "playing in mix" : processing ? "processing" : "not separated"}`}
                          key={clip.id}
                          draggable={Boolean(ready)}
                          onDragStart={(event) => {
                            if (!ready) { event.preventDefault(); return; }
                            draggedStem.current = { sourceClipId: clip.id, stemKind: stem.kind };
                            draggedTrack.current = null;
                            draggedClip.current = null;
                            event.dataTransfer.effectAllowed = "copy";
                            event.dataTransfer.setData("text/plain", `${stem.label} stem`);
                          }}
                          onDragEnd={() => { draggedStem.current = null; }}
                        >
                          <WaveformShape seed={clip.id + stemIndex + 1} muted={!ready || !laneAudible} responseScale={waveformResponseScale(clip, payload.project.master_gain_db)} />
                          <b>{ready ? laneState.solo ? "SOLO" : laneState.muted ? "MUTED" : "READY" : processing ? "PROCESSING" : "NOT SEPARATED"}</b>
                          <span className="stem-lane-controls">
                            <button
                              draggable={false}
                              className={laneState.muted ? "active mute" : ""}
                              disabled={!ready || clip.clip_kind !== "song"}
                              aria-label={`Mute ${stem.label}`}
                              aria-pressed={Boolean(laneState.muted)}
                              title={`Mute ${stem.label}`}
                              onPointerDown={(event) => event.stopPropagation()}
                              onClick={(event) => { event.stopPropagation(); void updateStemLaneState(clip.id, stem.kind, { muted: !laneState.muted }); }}
                            >M</button>
                            <button
                              draggable={false}
                              className={laneState.solo ? "active solo" : ""}
                              disabled={!ready || clip.clip_kind !== "song"}
                              aria-label={`Solo ${stem.label}`}
                              aria-pressed={Boolean(laneState.solo)}
                              title={`Solo ${stem.label}`}
                              onPointerDown={(event) => event.stopPropagation()}
                              onClick={(event) => { event.stopPropagation(); void updateStemLaneState(clip.id, stem.kind, { solo: !laneState.solo }); }}
                            >S</button>
                          </span>
                        </div>;
                      })}</div>)}
                    </div>}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <aside className="arrangement-inspector">
          <div className="arrangement-pane-title"><SlidersHorizontal size={16} /><div><strong>{selectedMarker ? "Cue inspector" : "Clip inspector"}</strong><span>{selectedMarker || selectedClip ? "Changes save automatically" : "Select a timeline item"}</span></div></div>
          {selectedMarker ? <>
            <section className="marker-identity">
              <span className={`marker-icon ${selectedMarker.color}`}>{selectedMarker.marker_kind === "section" ? <Flag size={15} weight="fill" /> : <MapPin size={15} weight="fill" />}</span>
              <div><strong>{selectedMarker.name}</strong><span>{selectedMarker.marker_kind === "section" ? "Timeline section" : "Timeline marker"}</span><small>{formatTime(selectedMarker.start_seconds)}{selectedMarker.end_seconds == null ? "" : ` to ${formatTime(selectedMarker.end_seconds)}`}</small></div>
            </section>
            <section className="inspector-section marker-properties">
              <h2>Details</h2>
              <label><span>Name</span><input aria-label="Cue name" type="text" value={selectedMarker.name} onChange={(event) => stageMarker(selectedMarker.id, { name: event.target.value })} onBlur={(event) => updateMarker(selectedMarker.id, { name: event.target.value })} /></label>
              <label><span>Start</span><input type="number" min="0" max={selectedMarker.end_seconds == null ? undefined : selectedMarker.end_seconds - 0.05} step="0.1" value={selectedMarker.start_seconds} onChange={(event) => stageMarker(selectedMarker.id, { start_seconds: Number(event.target.value) })} onBlur={(event) => updateMarker(selectedMarker.id, { start_seconds: Number(event.target.value) })} /><small>seconds</small></label>
              {selectedMarker.marker_kind === "section" && <label><span>End</span><input type="number" min={selectedMarker.start_seconds + 0.05} step="0.1" value={selectedMarker.end_seconds ?? selectedMarker.start_seconds + 1} onChange={(event) => stageMarker(selectedMarker.id, { end_seconds: Number(event.target.value) })} onBlur={(event) => updateMarker(selectedMarker.id, { end_seconds: Number(event.target.value) })} /><small>seconds</small></label>}
              <label><span>Color</span><select value={selectedMarker.color} onChange={(event) => updateMarker(selectedMarker.id, { color: event.target.value })}>{["violet", "cyan", "rose", "amber", "blue", "green", "red"].map((color) => <option value={color} key={color}>{color}</option>)}</select></label>
              <button className="delete-marker" disabled={busy} onClick={deleteMarker}><Trash size={13} /> Delete {selectedMarker.marker_kind}</button>
              <p>Markers and sections are saved with the project and included in project history.</p>
            </section>
          </> : selectedClip ? <>
            <section className="clip-identity"><span className={`source-color ${selectedClip.color}`} /><div><strong>{selectedClip.title}</strong><span>{selectedClip.artist || "Unknown artist"}</span><small>{selectedClip.source_bpm ?? "--"} BPM&nbsp;&nbsp; {selectedClip.source_key || "--"}</small></div></section>
            {selectedClipIds.length > 1 && <section className="inspector-section multi-edit-section">
              <h2>{selectedClipIds.length} clips selected</h2>
              <label><span>Gain</span><input aria-label="Selected clips gain" type="range" min="-24" max="12" step="0.5" value={selectedClip.gain_db} onChange={(event) => stageSelectedClips({ gain_db: Number(event.target.value) })} onPointerUp={(event) => batchUpdateSelected({ gain_db: Number(event.currentTarget.value) })} /><small>{selectedClip.gain_db.toFixed(1)} dB</small></label>
              <label><span>Color</span><select value={selectedClip.color} onChange={(event) => batchUpdateSelected({ color: event.target.value })}>{["violet", "cyan", "rose", "amber", "blue", "green", "red"].map((color) => <option value={color} key={color}>{color}</option>)}</select></label>
              <div className="multi-edit-actions"><button onClick={() => batchUpdateSelected({ muted: !selectedClips.every((clip) => clip.muted) })}>Mute all</button><button onClick={() => batchUpdateSelected({ locked: !selectedClips.every((clip) => clip.locked) })}>Lock all</button></div>
              <button className="multi-delete" disabled={selectedClips.some((clip) => clip.locked)} onClick={deleteSelectedClips}><Trash size={12} /> Delete selected</button>
              <button className="trim-selection-button" disabled={!hasSelection || selectedClips.some((clip) => clip.locked)} onClick={trimSelectedToSelection}><Scissors size={12} /> Trim to selection</button>
            </section>}
            <div className="clip-state-actions">
              <button className={selectedClip.muted ? "active" : ""} onClick={() => updateClip(selectedClip.id, { muted: !selectedClip.muted })}>{selectedClip.muted ? <SpeakerSlash size={14} /> : <SpeakerHigh size={14} />} Mute</button>
              <button className={selectedClip.solo ? "active" : ""} onClick={() => updateClip(selectedClip.id, { solo: !selectedClip.solo })}>S Solo</button>
              <button className={selectedClip.locked ? "active" : ""} onClick={() => updateClip(selectedClip.id, { locked: !selectedClip.locked })}>{selectedClip.locked ? <Lock size={14} /> : <LockOpen size={14} />} Lock</button>
            </div>
            <section className="inspector-section">
              <h2>Placement</h2>
              <label><span>Channel</span><select disabled={Boolean(selectedClip.locked)} value={selectedClip.channel} onChange={(event) => updateClip(selectedClip.id, { channel: Number(event.target.value) })}>{[1, 2, 3, 4].map((channel) => <option value={channel} key={channel}>Channel {channel}</option>)}</select></label>
              <label><span>Start</span><input disabled={Boolean(selectedClip.locked)} type="number" min="0" step="0.5" value={selectedClip.start_seconds} onChange={(event) => stageClip(selectedClip.id, { start_seconds: Number(event.target.value) })} onBlur={(event) => updateClip(selectedClip.id, { start_seconds: Number(event.target.value) })} /><small>seconds</small></label>
              <div className="nudge-row"><button aria-label="Move clip left 1 second" disabled={Boolean(selectedClip.locked)} onClick={() => updateClip(selectedClip.id, { start_seconds: Math.max(0, selectedClip.start_seconds - 1) })}><Minus size={13} /> -1s</button><button aria-label="Move clip right 1 second" disabled={Boolean(selectedClip.locked)} onClick={() => updateClip(selectedClip.id, { start_seconds: selectedClip.start_seconds + 1 })}><Plus size={13} /> +1s</button></div>
            </section>
            <section className="inspector-section clip-edit-section">
              <h2>Edit</h2>
              <div className="clip-edit-actions">
                <button disabled={busy} onClick={duplicateClip}><Copy size={13} /> Duplicate</button>
                <button aria-pressed={Boolean(selectedClip.loop_enabled)} className={selectedClip.loop_enabled ? "active" : ""} onClick={() => updateClip(selectedClip.id, { loop_enabled: !selectedClip.loop_enabled })}><Repeat size={13} /> Loop</button>
                <button aria-pressed={Boolean(selectedClip.reversed)} className={selectedClip.reversed ? "active" : ""} onClick={() => updateClip(selectedClip.id, { reversed: !selectedClip.reversed })}><ArrowCounterClockwise size={13} /> Reverse</button>
              </div>
              <div className="clip-consolidation-actions">
                {selectedClip.rendered_mode === "freeze"
                  ? <button disabled={busy || Boolean(selectedClip.locked)} onClick={() => consolidateSelectedClip("unfreeze")}>Unfreeze source</button>
                  : selectedClip.clip_kind !== "rendered" && <button disabled={busy || Boolean(selectedClip.locked) || !selectedRender} onClick={() => consolidateSelectedClip("freeze")}>Freeze source</button>}
                <button disabled={busy || Boolean(selectedClip.locked) || !selectedRender} onClick={() => consolidateSelectedClip("bounce")}>Bounce copy</button>
                {selectedClip.rendered_mode && <button onClick={revealConsolidatedSource}><FolderOpen size={13} /> Show audio file</button>}
              </div>
              <label><span>Source in</span><input disabled={Boolean(selectedClip.locked)} type="number" min="0" max={selectedClip.source_duration_seconds - selectedClip.duration_seconds * tempoFactor(selectedClip)} step="0.1" value={selectedClip.source_in_seconds} onChange={(event) => stageClip(selectedClip.id, { source_in_seconds: Number(event.target.value) })} onBlur={(event) => updateClip(selectedClip.id, { source_in_seconds: Number(event.target.value) })} /><small>seconds</small></label>
              <label><span>Duration</span><input disabled={Boolean(selectedClip.locked)} type="number" min={Math.max(0.05, selectedClip.fade_in_seconds + selectedClip.fade_out_seconds)} max={(selectedClip.source_duration_seconds - selectedClip.source_in_seconds) / tempoFactor(selectedClip)} step="0.1" value={selectedClip.duration_seconds} onChange={(event) => stageClip(selectedClip.id, { duration_seconds: Number(event.target.value) })} onBlur={(event) => updateClip(selectedClip.id, { duration_seconds: Number(event.target.value) })} /><small>seconds</small></label>
              <button className="split-playhead-control" title="Split at playhead S" disabled={busy || !canSplitAtPlayhead} onClick={splitClip}><Scissors size={13} /><span>Split at playhead</span><small>{canSplitAtPlayhead && splitOffset != null ? `+${splitOffset.toFixed(2)}s` : "Place playhead inside clip"}</small></button>
              <div className="crossfade-control">
                <select aria-label="Crossfade target clip" value={crossfadeTargetId ?? ""} onChange={(event) => setCrossfadeTargetId(event.target.value ? Number(event.target.value) : null)}>
                  {overlapCandidates.length === 0 && <option value="">No overlapping clip</option>}
                  {overlapCandidates.map((clip) => <option value={clip.id} key={clip.id}>CH {clip.channel} · {clip.title} · {formatTime(clip.start_seconds)}</option>)}
                </select>
                <button disabled={busy || Boolean(selectedClip.locked) || !crossfadeTargetId} onClick={crossfadeClip}><ArrowsOutLineHorizontal size={13} /> Crossfade</button>
              </div>
              <p>Freeze pins the prepared source while leaving gain, EQ, fades and placement editable. Bounce creates a consolidated copy immediately after this clip. The original file is never rewritten.</p>
              {clipNeedsRender(selectedClip) && <p className="reverse-note">Reverse, pitch and tempo changes are prepared automatically for accurate playback.</p>}
            </section>
            <section className="inspector-section">
              <h2>Sound</h2>
              <label><span>Gain</span><input aria-label="Clip gain" type="range" min="-24" max="12" step="0.5" value={selectedClip.gain_db} onChange={(event) => stageClip(selectedClip.id, { gain_db: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { gain_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { gain_db: Number(event.currentTarget.value) })} /><small>{selectedClip.gain_db.toFixed(1)} dB</small></label>
              <label><span>Pan</span><input aria-label="Clip pan" type="range" min="-1" max="1" step="0.05" value={selectedClip.pan} onChange={(event) => stageClip(selectedClip.id, { pan: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { pan: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { pan: Number(event.currentTarget.value) })} /><small>{selectedClip.pan === 0 ? "C" : selectedClip.pan < 0 ? `${Math.round(Math.abs(selectedClip.pan) * 100)}L` : `${Math.round(selectedClip.pan * 100)}R`}</small></label>
              <label><span>Pitch</span><input type="number" min="-24" max="24" step="1" value={selectedClip.pitch_semitones} onChange={(event) => stageClip(selectedClip.id, { pitch_semitones: Number(event.target.value) })} onBlur={(event) => updateClip(selectedClip.id, { pitch_semitones: Number(event.target.value) })} /><small>{transposeKeyLabel(selectedClip.source_key, selectedClip.pitch_semitones)}</small></label>
              <div className="key-match-control">
                <span>Match key to</span>
                <select aria-label="Key match target clip" value={keyMatchTarget?.id ?? ""} onChange={(event) => setKeyMatchTargetId(event.target.value ? Number(event.target.value) : null)}>
                  {keyMatchCandidates.length === 0 && <option value="">No keyed clip</option>}
                  {keyMatchCandidates.map((clip) => <option value={clip.id} key={clip.id}>CH {clip.channel} · {clip.title} · {transposeKeyLabel(clip.source_key, clip.pitch_semitones)}</option>)}
                </select>
                <button disabled={Boolean(selectedClip.locked) || !selectedKeyMatch || selectedKeyMatch.delta === 0} onClick={matchSelectedClipKey}>
                  {selectedKeyMatch ? selectedKeyMatch.delta === 0 ? "Keys already compatible" : `Shift ${selectedKeyMatch.delta > 0 ? "+" : ""}${selectedKeyMatch.delta} → ${selectedKeyMatch.resultingKey}` : "Match selected clip"}
                </button>
              </div>
              {selectedKeyMatch?.relativeModeMatch && <p className="key-match-note">The target uses a different mode, so Decksmith matches its relative compatible key instead of pretending pitch can change major into minor.</p>}
              <label><span>Target BPM</span><input aria-label="Clip target BPM" disabled={Boolean(selectedClip.locked) || clipTargetBpm(selectedClip) == null} type="number" min={selectedClip.source_bpm ? selectedClip.source_bpm * 0.25 : undefined} max={selectedClip.source_bpm ? selectedClip.source_bpm * 4 : undefined} step="0.01" value={clipTargetBpm(selectedClip)?.toFixed(3) ?? ""} onChange={(event) => stageClipTargetBpm(selectedClip, Number(event.target.value))} onBlur={(event) => commitClipTargetBpm(selectedClip, Number(event.target.value))} /><small>{selectedClip.tempo_percent.toFixed(3)}%</small></label>
              <div className="tempo-match-control"><span>Project tempo</span><button disabled={Boolean(selectedClip.locked) || clipTargetBpm(selectedClip) == null} onClick={() => commitClipTargetBpm(selectedClip, payload.project.tempo)}>Match {payload.project.tempo.toFixed(2)} BPM</button></div>
              <p className="tempo-help">Shift-drag the clip’s right edge to retime it. Pull outward to slow down; push inward to speed up. The source span stays unchanged.</p>
              <label><span>Fade in</span><input aria-label="Fade in duration" type="range" min="0" max={Math.max(0, selectedClip.duration_seconds - selectedClip.fade_out_seconds)} step="0.1" value={selectedClip.fade_in_seconds} onChange={(event) => stageClip(selectedClip.id, { fade_in_seconds: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { fade_in_seconds: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { fade_in_seconds: Number(event.currentTarget.value) })} /><small>{selectedClip.fade_in_seconds.toFixed(1)}s</small></label>
              <label><span>Fade out</span><input aria-label="Fade out duration" type="range" min="0" max={Math.max(0, selectedClip.duration_seconds - selectedClip.fade_in_seconds)} step="0.1" value={selectedClip.fade_out_seconds} onChange={(event) => stageClip(selectedClip.id, { fade_out_seconds: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { fade_out_seconds: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { fade_out_seconds: Number(event.currentTarget.value) })} /><small>{selectedClip.fade_out_seconds.toFixed(1)}s</small></label>
            </section>
            <section className="inspector-section tone-dynamics-section">
              <h2>Tone &amp; dynamics</h2>
              <label><span>Low</span><input aria-label="Clip low EQ" type="range" min="-12" max="12" step="0.5" value={selectedClip.eq_low_db} onChange={(event) => stageClip(selectedClip.id, { eq_low_db: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { eq_low_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { eq_low_db: Number(event.currentTarget.value) })} /><small>{selectedClip.eq_low_db > 0 ? "+" : ""}{selectedClip.eq_low_db.toFixed(1)} dB</small></label>
              <label><span>Mid</span><input aria-label="Clip mid EQ" type="range" min="-12" max="12" step="0.5" value={selectedClip.eq_mid_db} onChange={(event) => stageClip(selectedClip.id, { eq_mid_db: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { eq_mid_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { eq_mid_db: Number(event.currentTarget.value) })} /><small>{selectedClip.eq_mid_db > 0 ? "+" : ""}{selectedClip.eq_mid_db.toFixed(1)} dB</small></label>
              <label><span>High</span><input aria-label="Clip high EQ" type="range" min="-12" max="12" step="0.5" value={selectedClip.eq_high_db} onChange={(event) => stageClip(selectedClip.id, { eq_high_db: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { eq_high_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { eq_high_db: Number(event.currentTarget.value) })} /><small>{selectedClip.eq_high_db > 0 ? "+" : ""}{selectedClip.eq_high_db.toFixed(1)} dB</small></label>
              <label><span>High-pass</span><input aria-label="Clip high-pass frequency" type="range" min="20" max={Math.min(5000, selectedClip.lowpass_hz - 10)} step="10" value={selectedClip.highpass_hz} onChange={(event) => stageClip(selectedClip.id, { highpass_hz: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { highpass_hz: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { highpass_hz: Number(event.currentTarget.value) })} /><small>{Math.round(selectedClip.highpass_hz)} Hz</small></label>
              <label><span>Low-pass</span><input aria-label="Clip low-pass frequency" type="range" min={Math.max(1000, selectedClip.highpass_hz + 10)} max="20000" step="100" value={selectedClip.lowpass_hz} onChange={(event) => stageClip(selectedClip.id, { lowpass_hz: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { lowpass_hz: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { lowpass_hz: Number(event.currentTarget.value) })} /><small>{selectedClip.lowpass_hz >= 1000 ? `${(selectedClip.lowpass_hz / 1000).toFixed(1)}k` : Math.round(selectedClip.lowpass_hz)} Hz</small></label>
              <button className={selectedClip.compressor_enabled ? "master-limiter active" : "master-limiter"} aria-pressed={Boolean(selectedClip.compressor_enabled)} onClick={() => updateClip(selectedClip.id, { compressor_enabled: !selectedClip.compressor_enabled })}>Compressor {selectedClip.compressor_enabled ? "on" : "off"}</button>
              {Boolean(selectedClip.compressor_enabled) && <>
                <label><span>Threshold</span><input aria-label="Clip compressor threshold" type="range" min="-60" max="0" step="1" value={selectedClip.compressor_threshold_db} onChange={(event) => stageClip(selectedClip.id, { compressor_threshold_db: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { compressor_threshold_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { compressor_threshold_db: Number(event.currentTarget.value) })} /><small>{selectedClip.compressor_threshold_db.toFixed(0)} dB</small></label>
                <label><span>Ratio</span><input aria-label="Clip compressor ratio" type="range" min="1" max="20" step="0.5" value={selectedClip.compressor_ratio} onChange={(event) => stageClip(selectedClip.id, { compressor_ratio: Number(event.target.value) })} onPointerUp={(event) => updateClip(selectedClip.id, { compressor_ratio: Number(event.currentTarget.value) })} onKeyUp={(event) => updateClip(selectedClip.id, { compressor_ratio: Number(event.currentTarget.value) })} /><small>{selectedClip.compressor_ratio.toFixed(1)}:1</small></label>
              </>}
              <button className="reset-tone-button" onClick={() => updateClip(selectedClip.id, { eq_low_db: 0, eq_mid_db: 0, eq_high_db: 0, highpass_hz: 20, lowpass_hz: 20000, compressor_enabled: false, compressor_threshold_db: -18, compressor_ratio: 4 })}>Reset tone</button>
              <p>Processing is non-destructive and follows this clip when it is duplicated, split or turned into a stem clip.</p>
            </section>
            <section className="inspector-section render-engine-section">
              <h2>Playback audio</h2>
              <div className={`render-engine-status ${selectedRender ? "ready" : selectedRenderBusy ? "running" : selectedRenderJob?.status ?? "idle"}`}>
                <Waveform size={15} weight={selectedRender ? "fill" : "regular"} />
                <span>
                  <strong>{selectedRender ? "Sample-accurate audio ready" : selectedRenderBusy ? "Preparing automatically" : selectedRenderJob?.status === "failed" ? "Audio preparation failed" : "Waiting to prepare"}</strong>
                  <small>{selectedRender ? `${selectedRender.duration_seconds.toFixed(3)}s · decoded PCM` : selectedRenderBusy ? (selectedRenderProgress?.phase ?? "preparing") : selectedRenderJob?.error ?? renderStatus?.capability.message ?? "Checking local audio engine"}</small>
                </span>
              </div>
              {selectedRenderBusy && <div className="render-progress"><i style={{ width: `${Math.max(6, Math.round((selectedRenderProgress?.progress ?? 0) * 100))}%` }} /></div>}
              <div className="render-engine-actions">
                {selectedRenderBusy
                  ? <button onClick={cancelActiveRender}>Cancel preparation</button>
                  : selectedRenderJob?.status === "failed" && <button disabled={!renderStatus?.capability.available || renderingClipId != null} onClick={() => renderClipPreview(selectedClip, true)}>Retry preparation</button>}
              </div>
              <p>Decksmith prepares local PCM automatically so the waveform, playhead and sound use the same sample timeline. The original file remains unchanged.</p>
            </section>
            <section className="inspector-section">
              <h2>Structure</h2>
              <div className="group-actions"><button disabled={selectedClipIds.length < 2} onClick={groupSelectedClips}>Group {selectedClipIds.length > 1 ? selectedClipIds.length : "clips"}</button><button disabled={selectedClip.group_id == null} onClick={ungroupSelectedClips}>Ungroup</button></div>
              <div className="group-actions"><button disabled={selectedClip.group_id == null} onClick={() => shiftSelectedGroup(-1)}>Channels up</button><button disabled={selectedClip.group_id == null} onClick={() => shiftSelectedGroup(1)}>Channels down</button></div>
              {selectedClipIds.length === 1 && <button className="trim-selection-button" disabled={!hasSelection || Boolean(selectedClip.locked)} onClick={trimSelectedToSelection}><Scissors size={12} /> Trim clip to selection</button>}
            </section>
            <section className="inspector-section stem-engine-section">
              <h2>Stems</h2>
              <button className="expand-stems" onClick={() => updateClip(selectedClip.id, { expanded: !selectedClip.expanded })}>{selectedClip.expanded ? <CaretDown size={14} /> : <CaretRight size={14} />} {selectedClip.expanded ? "Hide stem lanes" : "Reveal stem lanes"}</button>
              <div className={`stem-engine-status ${selectedStemsReady ? "ready" : selectedStemBusy ? "running" : selectedStemJob?.status ?? "idle"}`}>
                <Waveform size={15} weight={selectedStemsReady ? "fill" : "regular"} />
                <span>
                  <strong>{selectedStemsReady ? "Four editable stems ready" : selectedStemBusy ? "Separating locally" : selectedStemJob?.status === "failed" ? "Separation failed" : stemStatus?.capability.available ? "Ready to separate" : "Stem engine unavailable"}</strong>
                  <small>{selectedStemsReady ? `${stemStatus?.model ?? "htdemucs"} · source-safe cache` : selectedStemBusy ? `${selectedStemProgress?.phase ?? "preparing"} · ${Math.round((selectedStemProgress?.progress ?? 0) * 100)}% · usually 1–3 min` : selectedStemJob?.error ?? stemStatus?.capability.message ?? "Checking local engine"}</small>
                </span>
              </div>
              {selectedStemBusy && <div className="stem-progress"><i style={{ width: `${Math.max(6, Math.round((selectedStemProgress?.progress ?? 0) * 100))}%` }} /></div>}
              {selectedStemsReady && <>
                <div className="stem-source-picker">
                  <span>Selected clip source</span>
                  <button className={selectedClip.clip_kind === "song" ? "active" : ""} disabled={Boolean(selectedClip.locked) || selectedClip.clip_kind === "rendered"} onClick={() => setSelectedClipSource("song")}>Full song</button>
                  <strong>{clipSourceLabel(selectedClip.clip_kind)}</strong>
                </div>
                <label className="stem-channel-picker"><span>Add stems to</span><select aria-label="Stem output channel" value={stemTargetChannel} onChange={(event) => setStemTargetChannel(Number(event.target.value))}>{[1, 2, 3, 4].map((channel) => <option value={channel} key={channel}>Channel {channel}</option>)}</select></label>
                <div className="stem-workflow-grid">{stemDefinitions.map(({ kind, label }) => {
                  const asset = selectedStemAssets.find((stem) => stem.stem_kind === kind);
                  const laneState = stemLaneState(selectedClip, kind);
                  return <div className={selectedClip.clip_kind === kind ? "stem-workflow-row active" : "stem-workflow-row"} key={kind}>
                    <strong>{label}</strong>
                    <button className={laneState.muted ? "active stem-mute" : ""} aria-label={`Mute ${label}`} aria-pressed={Boolean(laneState.muted)} disabled={!asset || selectedClip.clip_kind !== "song"} onClick={() => updateStemLaneState(selectedClip.id, kind, { muted: !laneState.muted })}>M</button>
                    <button className={laneState.solo ? "active stem-solo" : ""} aria-label={`Solo ${label}`} aria-pressed={Boolean(laneState.solo)} disabled={!asset || selectedClip.clip_kind !== "song"} onClick={() => updateStemLaneState(selectedClip.id, kind, { solo: !laneState.solo })}>S</button>
                    <button className={previewingStemKind === kind ? "active" : ""} disabled={!asset} onClick={() => asset && previewStem(asset)}>{previewingStemKind === kind ? <Pause size={11} weight="fill" /> : <Play size={11} weight="fill" />} Preview</button>
                    <button disabled={!asset || Boolean(selectedClip.locked) || selectedClip.clip_kind === kind || selectedClip.clip_kind === "rendered"} onClick={() => setSelectedClipSource(kind)}>Use only</button>
                    <button disabled={!asset || busy} onClick={() => addSelectedStemToArrangement(kind)}><Plus size={10} /> Add CH {stemTargetChannel}</button>
                  </div>;
                })}</div>
                {selectedClip.clip_kind === "song" && <div className="stem-mix-summary"><span>Now playing</span><strong>{audibleStemKinds(selectedClip).map((kind) => stemDefinitions.find((stem) => stem.kind === kind)?.label).join(" + ") || "Silence"}</strong></div>}
              </>}
              <div className="stem-engine-actions">
                {selectedStemBusy ? <button onClick={cancelSelectedStemSeparation}>Cancel</button> : <button disabled={!stemStatus?.capability.available} onClick={() => separateSelectedTrackStems(selectedStemsReady)}>{selectedStemsReady ? "Regenerate stems" : selectedStemJob?.status === "failed" ? "Retry separation" : "Separate stems"}</button>}
              </div>
              <p>Use only replaces this clip’s source with one isolated stem. Add creates a separate clip that can be moved, trimmed, duplicated, muted, soloed and processed independently. The original track is never modified.</p>
            </section>
            <section className="inspector-section master-section">
              <h2>Project master</h2>
              <label><span>Key</span><input aria-label="Project musical key" type="text" maxLength={12} value={payload.project.musical_key} onChange={(event) => setPayload({ ...payload, project: { ...payload.project, musical_key: event.target.value.toUpperCase() } })} onBlur={(event) => updateMaster({ musical_key: event.target.value })} /><small>context</small></label>
              <label><span>Gain</span><input aria-label="Master gain" type="range" min="-24" max="12" step="0.5" value={payload.project.master_gain_db} onChange={(event) => stageMaster({ master_gain_db: Number(event.target.value) })} onPointerUp={(event) => updateMaster({ master_gain_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateMaster({ master_gain_db: Number(event.currentTarget.value) })} /><small>{payload.project.master_gain_db.toFixed(1)} dB</small></label>
              <label><span>Low</span><input aria-label="Master low EQ" type="range" min="-12" max="12" step="0.5" value={payload.project.master_low_eq_db} onChange={(event) => stageMaster({ master_low_eq_db: Number(event.target.value) })} onPointerUp={(event) => updateMaster({ master_low_eq_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateMaster({ master_low_eq_db: Number(event.currentTarget.value) })} /><small>{payload.project.master_low_eq_db > 0 ? "+" : ""}{payload.project.master_low_eq_db.toFixed(1)} dB</small></label>
              <label><span>Mid</span><input aria-label="Master mid EQ" type="range" min="-12" max="12" step="0.5" value={payload.project.master_mid_eq_db} onChange={(event) => stageMaster({ master_mid_eq_db: Number(event.target.value) })} onPointerUp={(event) => updateMaster({ master_mid_eq_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateMaster({ master_mid_eq_db: Number(event.currentTarget.value) })} /><small>{payload.project.master_mid_eq_db > 0 ? "+" : ""}{payload.project.master_mid_eq_db.toFixed(1)} dB</small></label>
              <label><span>High</span><input aria-label="Master high EQ" type="range" min="-12" max="12" step="0.5" value={payload.project.master_high_eq_db} onChange={(event) => stageMaster({ master_high_eq_db: Number(event.target.value) })} onPointerUp={(event) => updateMaster({ master_high_eq_db: Number(event.currentTarget.value) })} onKeyUp={(event) => updateMaster({ master_high_eq_db: Number(event.currentTarget.value) })} /><small>{payload.project.master_high_eq_db > 0 ? "+" : ""}{payload.project.master_high_eq_db.toFixed(1)} dB</small></label>
              <label><span>Width</span><input aria-label="Master stereo width" type="range" min="0" max="2" step="0.05" value={payload.project.master_stereo_width} onChange={(event) => stageMaster({ master_stereo_width: Number(event.target.value) })} onPointerUp={(event) => updateMaster({ master_stereo_width: Number(event.currentTarget.value) })} onKeyUp={(event) => updateMaster({ master_stereo_width: Number(event.currentTarget.value) })} /><small>{Math.round(payload.project.master_stereo_width * 100)}%</small></label>
              <label><span>Target</span><input aria-label="Project loudness target" type="number" min="-24" max="-6" step="1" value={payload.project.target_lufs} onChange={(event) => setPayload({ ...payload, project: { ...payload.project, target_lufs: Number(event.target.value) } })} onBlur={(event) => updateMaster({ target_lufs: Number(event.target.value) })} /><small>LUFS</small></label>
              <button className={payload.project.master_limiter_enabled ? "master-limiter active" : "master-limiter"} aria-pressed={Boolean(payload.project.master_limiter_enabled)} onClick={() => updateMaster({ master_limiter_enabled: payload.project.master_limiter_enabled ? 0 : 1 })}>Limiter {payload.project.master_limiter_enabled ? "on" : "off"}</button>
              <div className="live-meter"><span>Preview level</span><div><i style={{ width: `${Math.max(0, Math.min(100, ((liveMeterDb + 60) / 60) * 100))}%` }} /></div><strong>{liveMeterDb <= -59.9 ? "−∞" : `${liveMeterDb.toFixed(1)} dB`}</strong></div>
              <div className={`headroom-status ${estimatedPeakDb > 0 ? "warning" : "safe"}`}><span>Pre-effects estimate</span><strong>{Number.isFinite(estimatedPeakDb) ? `${estimatedPeakDb > 0 ? "+" : ""}${estimatedPeakDb.toFixed(1)} dBFS` : "No signal"}</strong><small>{estimatedPeakDb > 0 ? (payload.project.master_limiter_enabled ? "Limiter will catch the predicted overage" : "Reduce gain or enable the limiter") : "Live meter includes the active EQ and dynamics"}</small></div>
            </section>
            <section className="inspector-section smart-render-section">
              <h2>Smart Render</h2>
              <button className="smart-render-run" disabled={smartRenderRunning || renderPendingCount > 0 || payload.clips.length === 0} onClick={runSmartRender}>
                <Waveform size={13} /> {smartRenderRunning ? "Analysing final mix…" : smartRenderReport ? "Run checks again" : "Analyse before export"}
              </button>
              {renderPendingCount > 0 && <p>Checks unlock when every audible clip has finished preparing.</p>}
              {!smartRenderReport && renderPendingCount === 0 && <p>Measures the actual processed mix for LUFS, true peak and silence, then checks the timeline for vocal collisions, bass masking and abrupt transitions.</p>}
              {smartRenderReport && <>
                <div className={`smart-render-summary ${smartRenderReport.status}`}>
                  <strong>{smartRenderReport.status === "ready" ? "Ready to export" : smartRenderReport.status === "blocked" ? "Fix before export" : "Review recommended"}</strong>
                  <span>{smartRenderReport.counts.error} errors · {smartRenderReport.counts.warning} warnings · {smartRenderReport.counts.info} notes</span>
                </div>
                <div className="smart-render-metrics">
                  <div><span>Integrated</span><strong>{smartRenderReport.metrics.integrated_lufs == null ? "No signal" : `${smartRenderReport.metrics.integrated_lufs.toFixed(1)} LUFS`}</strong></div>
                  <div><span>True peak</span><strong>{smartRenderReport.metrics.true_peak_dbfs == null ? "—" : `${smartRenderReport.metrics.true_peak_dbfs > 0 ? "+" : ""}${smartRenderReport.metrics.true_peak_dbfs.toFixed(2)} dBTP`}</strong></div>
                  <div><span>Range</span><strong>{smartRenderReport.metrics.loudness_range_lu == null ? "—" : `${smartRenderReport.metrics.loudness_range_lu.toFixed(1)} LU`}</strong></div>
                </div>
                {smartRenderReport.metrics.recommended_master_gain_db != null && Math.abs(smartRenderReport.metrics.recommended_master_gain_db - payload.project.master_gain_db) >= 0.05 && <button className="apply-loudness-button" onClick={() => updateMaster({ master_gain_db: smartRenderReport.metrics.recommended_master_gain_db ?? payload.project.master_gain_db })}>Try {smartRenderReport.metrics.recommended_master_gain_db > 0 ? "+" : ""}{smartRenderReport.metrics.recommended_master_gain_db.toFixed(2)} dB toward {payload.project.target_lufs.toFixed(0)} LUFS</button>}
                <div className="smart-render-issues">
                  {smartRenderReport.issues.length === 0 && <div className="smart-render-clean"><strong>No issues found</strong><span>The rendered signal and timeline checks passed.</span></div>}
                  {smartRenderReport.issues.map((issue, index) => <button className={`smart-render-issue ${issue.severity}`} onClick={() => revealSmartRenderIssue(issue)} key={`${issue.code}-${issue.start_seconds ?? "global"}-${index}`}>
                    <i>{issue.severity === "error" ? "!" : issue.severity === "warning" ? "△" : "i"}</i>
                    <span><strong>{issue.title}</strong><small>{issue.detail}</small>{issue.start_seconds != null && <em>{formatTime(issue.start_seconds)}{issue.end_seconds == null ? "" : `–${formatTime(issue.end_seconds)}`}</em>}</span>
                  </button>)}
                </div>
              </>}
            </section>
            <section className="inspector-section audio-export-section">
              <h2>Export mixdown</h2>
              <button className={loudnessTargetedExport ? "targeted-export-toggle active" : "targeted-export-toggle"} disabled={!smartRenderReport?.fresh || smartRenderReport.metrics.normalization_offset_db == null} aria-pressed={loudnessTargetedExport} onClick={() => setLoudnessTargetedExport((value) => !value)}>
                {loudnessTargetedExport ? `Loudness-targeted · ${payload.project.target_lufs.toFixed(0)} LUFS` : "Original mastered level"}
              </button>
              <div className="audio-export-actions">
                <button disabled={renderPendingCount > 0 || exportingFormat != null || payload.clips.length === 0} onClick={() => exportProjectAudio("wav")}><DownloadSimple size={13} /> {exportingFormat === "wav" ? "Exporting WAV…" : "WAV · 24-bit"}</button>
                <button disabled={renderPendingCount > 0 || exportingFormat != null || payload.clips.length === 0} onClick={() => exportProjectAudio("mp3")}><DownloadSimple size={13} /> {exportingFormat === "mp3" ? "Exporting MP3…" : "MP3 · High quality"}</button>
              </div>
              {renderPendingCount > 0 && <p>Export unlocks when every audible clip has finished preparing.</p>}
              {loudnessTargetedExport && <p>Creates a separate two-pass loudness-targeted derivative. The project master and previous exports remain unchanged.</p>}
              {!loudnessTargetedExport && <p>The original mastered level is preserved exactly. Run Smart Render to unlock a separate loudness-targeted derivative.</p>}
              {lastAudioExport && <div className="audio-export-result"><strong>{lastAudioExport.format.toUpperCase()} exported · {lastAudioExport.export_mode === "loudness_targeted" ? `${lastAudioExport.target_lufs?.toFixed(0)} LUFS derivative` : "original level"}</strong><span>{lastAudioExport.clip_count} clips · {formatTime(lastAudioExport.duration_seconds)} · {(lastAudioExport.file_size / 1_000_000).toFixed(1)} MB</span><small title={lastAudioExport.path}>{lastAudioExport.path}</small></div>}
              {audioExportHistory.length > 0 && <div className="audio-export-history">
                <strong>Recent exports</strong>
                {audioExportHistory.slice(0, 5).map((item) => <div className={item.exists ? "" : "missing"} key={item.id}>
                  <span>{item.format.toUpperCase()} · {item.export_mode === "loudness_targeted" ? `${item.target_lufs?.toFixed(0)} LUFS` : "Original"}</span>
                  <small>{new Date(item.created_at).toLocaleDateString()} · {(item.file_size / 1_000_000).toFixed(1)} MB{item.exists ? "" : " · Missing"}</small>
                  <em title={item.destination_path}>{item.destination_path}</em>
                </div>)}
              </div>}
              <p>The mixdown uses the exact prepared song or stem audio with the same clip EQ, filters, compression, placement, fades, master EQ, width, gain and limiter heard in arrangement playback.</p>
            </section>
          </> : <div className="inspector-empty"><ArrowsLeftRight size={24} /><p>Select a clip, marker or section to edit it.</p></div>}
        </aside>
      </section>

      <footer className="arrangement-transport">
        <div className="transport-project"><strong>{payload.project.name}</strong><span>{previewing ? `${activeAuditionCount} sounding · ` : ""}{payload.clips.length} clips across 4 channels{renderPendingCount ? ` · preparing ${renderPendingCount} local audio file${renderPendingCount === 1 ? "" : "s"}` : " · audio ready"}</span></div>
        <div className="arrangement-playback"><button aria-label={previewing ? "Pause timeline audition" : "Play timeline audition"} disabled={!renderStatus?.renders.length} onClick={toggleTimelineAudition}>{previewing ? <Pause size={17} weight="fill" /> : <Play size={17} weight="fill" />}</button><span>{formatTime(timelinePosition)}</span><div><i style={{ width: `${Math.min(100, (timelinePosition / Math.max(1, timelineDuration)) * 100)}%` }} /></div><small>{formatTime(timelineDuration)}</small></div>
      </footer>
    </>
  );
}
