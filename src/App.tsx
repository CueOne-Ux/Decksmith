import { useEffect, useMemo, useRef, useState } from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open } from "@tauri-apps/plugin-dialog";
import { ArrangementWorkspace } from "./ArrangementWorkspace";
import { ForgeWorkspace } from "./ForgeWorkspace";
import {
  ArrowsDownUp,
  ArrowsClockwise,
  ArrowRight,
  ArrowDown,
  ArrowUp,
  CaretDown,
  CaretRight,
  Check,
  ClockCounterClockwise,
  Copy,
  Database,
  DotsThree,
  FileText,
  Folder,
  FolderOpen,
  Gear,
  GridFour,
  Headphones,
  Heart,
  ListBullets,
  ListPlus,
  MagnifyingGlass,
  MusicNotes,
  Pause,
  Play,
  Plus,
  Queue,
  Shuffle,
  ShieldCheck,
  SidebarSimple,
  SkipBack,
  SkipForward,
  SlidersHorizontal,
  Sparkle,
  SquaresFour,
  Star,
  Tag,
  Trash,
  UploadSimple,
  Warning,
  Waveform,
  X,
} from "@phosphor-icons/react";

type Track = {
  id: number;
  title: string;
  artist: string;
  album: string;
  bpm: number;
  key: string;
  genre: string;
  duration: string;
  added: string;
  rating: number;
  color: string;
  energy: string;
  mood?: string;
  path?: string;
  tags?: string[];
  fileSize?: number;
  missing?: boolean;
  addedAt?: string;
  year?: string;
  comment?: string;
  analysisStatus?: string;
  analysisStrength?: number | null;
  lastPlayedAt?: string | null;
  playCount?: number;
  updatedAt?: string;
};

type NativeTrack = {
  id: number;
  title: string;
  artist: string;
  album: string;
  genre: string;
  duration_seconds: number | null;
  bpm: number | null;
  musical_key: string;
  path: string;
  file_size: number;
  rating: number;
  color_tag: string;
  tags: string;
  missing: number;
  discovered_at: string;
  year: string;
  comment: string;
  analysis_status: string;
  analysis_strength: number | null;
  energy_score: number | null;
  last_played_at: string | null;
  play_count: number;
  mood: string;
  updated_at: string;
};

type ScanResult = {
  root: string;
  files_seen: number;
  tracks_added: number;
  tracks_updated: number;
  files_skipped: number;
  errors: number;
  cancelled: boolean;
};

type ScanProgressEvent = {
  event: "progress" | "complete";
  data: ScanResult;
  current_file?: string;
};

type AnalysisResult = {
  total: number;
  processed: number;
  completed: number;
  failed: number;
  cancelled: boolean;
  current_file: string;
};

type AnalysisProgressEvent = { event: "progress" | "complete"; data: AnalysisResult };

type MusicFolder = { id: number; path: string; last_scanned_at: string | null; track_count: number; missing_count: number };
type LibraryIssues = { missing: Array<{ id: number; path: string; title: string; artist: string }>; metadata_errors: Array<{ id: number; path: string; title: string; artist: string; metadata_error: string }> };
type DuplicateGroup = { hash: string; file_size: number; tracks: Array<{ id: number; path: string; title: string; artist: string }> };
type SeratoCrate = { id: number; name: string; hierarchy_path: string; track_count: number; matched_count: number; library_path: string };
type SmartPlaylist = { id: number; name: string; rules: Record<string, string | number | boolean>; track_count: number; created_at: string; updated_at: string };
type TransferWarning = { code: string; severity: "warning" | "error"; message: string };
type TransferChange = {
  crate_id: number | null;
  source_path: string;
  name: string;
  hierarchy_path: string;
  status: "added" | "modified" | "unchanged" | "removed";
  track_count: number;
  matched_count: number;
  added_tracks: number;
  removed_tracks: number;
  reordered: boolean;
  warnings: TransferWarning[];
};
type TransferPlan = {
  snapshot_id: number;
  previous_snapshot_id: number | null;
  created_at: string;
  libraries: number;
  crates: number;
  tracks: number;
  errors: number;
  summary: Record<"added" | "modified" | "unchanged" | "removed", number>;
  changes: TransferChange[];
  metadata_coverage: Record<"tracks" | "bpm" | "key" | "comments" | "ratings" | "marker_tracks" | "cue_tracks" | "cue_points" | "loop_records" | "marker_failures", number>;
  metadata_limits: Array<{ field: string; status: string; message: string }>;
};
type TransferExport = { id: number; destination_path: string; crate_count: number; track_count: number; warning_count: number; cue_count: number; loop_count: number; validation_status: string; manifest_path: string; created_at: string };
type TransferExportResult = { export_id: number; destination_path: string; xml_path: string; report_path: string; manifest_path: string; crate_count: number; track_count: number; cue_count: number; loop_count: number; validation_status: string; warning_count: number; warnings: TransferWarning[] };
type SortKey = "title" | "artist" | "bpm" | "key" | "genre" | "duration";
type CacheStatus = {
  root: string;
  total_bytes: number;
  reclaimable_bytes: number;
  removed_bytes?: number;
  removed_files?: number;
  categories: Record<string, { bytes: number; files: number; reclaimable_bytes: number; reclaimable_files: number }>;
};

const seedTimestamp = new Date().toISOString().slice(0, 19).replace("T", " ");
const moodOptions = ["Uplifting", "Driving", "Deep", "Dark", "Warm", "Euphoric", "Melodic", "Percussive"];

const seedTracks: Track[] = [
  { id: 1, title: "Abantu", artist: "Thakzin", album: "Abantu", bpm: 118, key: "8A", genre: "Afro House", duration: "06:18", added: "Today", rating: 5, color: "violet", energy: "Peak" },
  { id: 2, title: "Mina Nawe", artist: "Caiiro, Pixie L", album: "Pyramids", bpm: 120, key: "7A", genre: "Afro House", duration: "07:04", added: "Today", rating: 4, color: "cyan", energy: "High" },
  { id: 3, title: "Khombo", artist: "Darque", album: "More Life", bpm: 116, key: "9A", genre: "Afro Tech", duration: "05:46", added: "Yesterday", rating: 5, color: "amber", energy: "High" },
  { id: 4, title: "Ngiyamthanda", artist: "Dlala Thukzin", album: "Permanent Music", bpm: 114, key: "6A", genre: "Amapiano", duration: "06:31", added: "Yesterday", rating: 3, color: "rose", energy: "Warm" },
  { id: 5, title: "Sondela", artist: "Lemon & Herb", album: "Aura", bpm: 121, key: "10A", genre: "Afro House", duration: "07:22", added: "8 Jul", rating: 4, color: "blue", energy: "Peak" },
  { id: 6, title: "The Calling", artist: "Da Capo", album: "Indigo Child", bpm: 119, key: "8B", genre: "Deep House", duration: "06:57", added: "7 Jul", rating: 5, color: "violet", energy: "Build" },
  { id: 7, title: "Uhambo", artist: "Shimza", album: "Uhambo", bpm: 122, key: "9A", genre: "Afro Tech", duration: "06:09", added: "5 Jul", rating: 4, color: "cyan", energy: "Peak" },
  { id: 8, title: "Sunset Ritual", artist: "Enoo Napa", album: "The Journey", bpm: 117, key: "7B", genre: "Deep House", duration: "08:12", added: "3 Jul", rating: 4, color: "amber", energy: "Warm" },
].map((track, index) => ({
  ...track,
  mood: moodOptions[index % moodOptions.length],
  addedAt: seedTimestamp,
  updatedAt: seedTimestamp,
  lastPlayedAt: index < 2 ? seedTimestamp : null,
  playCount: index < 2 ? 1 : 0,
}));

const crates = [
  { name: "All tracks", count: 2847, icon: MusicNotes },
  { name: "Recently added", count: 84, icon: ClockCounterClockwise },
  { name: "Recently modified", count: 0, icon: ArrowsClockwise },
  { name: "Recently played", count: 0, icon: Headphones },
  { name: "Favourites", count: 126, icon: Heart },
];

const playlists = [
  { name: "Afro House", count: 342, color: "violet" },
  { name: "Amapiano", count: 275, color: "cyan" },
  { name: "Sunset Openers", count: 48, color: "amber" },
  { name: "Peak Time", count: 91, color: "rose" },
  { name: "Wedding Essentials", count: 187, color: "blue" },
];

function WaveformBars({ color = "violet" }: { color?: string }) {
  const bars = [4, 8, 13, 7, 16, 20, 9, 15, 6, 18, 12, 5, 11, 19, 8, 14, 6, 17, 10, 4, 12, 7, 15, 9, 5, 11, 6, 13];
  return (
    <div className={`mini-wave mini-wave-${color}`} aria-hidden="true">
      {bars.map((height, index) => <i key={index} style={{ height }} />)}
    </div>
  );
}

function isDesktop() {
  return "__TAURI_INTERNALS__" in window;
}

async function controlWindow(action: "close" | "minimize" | "maximize") {
  if (!isDesktop()) return;
  const appWindow = getCurrentWindow();
  if (action === "close") await appWindow.close();
  else if (action === "minimize") await appWindow.minimize();
  else await appWindow.toggleMaximize();
}

function formatDuration(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds)) return "--:--";
  const rounded = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  return `${String(minutes).padStart(2, "0")}:${String(rounded % 60).padStart(2, "0")}`;
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function energyLabel(score: number | null) {
  if (score === null) return "Pending";
  if (score >= 0.78) return "Peak";
  if (score >= 0.55) return "High";
  if (score >= 0.32) return "Warm";
  return "Low";
}

function isRecent(value?: string | null, days = 7) {
  if (!value) return false;
  const timestamp = new Date(`${value.replace(" ", "T")}Z`).getTime();
  return Number.isFinite(timestamp) && Date.now() - timestamp <= days * 24 * 60 * 60 * 1000;
}

function currentSqliteTimestamp() {
  return new Date().toISOString().slice(0, 19).replace("T", " ");
}

function mapNativeTracks(items: NativeTrack[]): Track[] {
  const colors = ["violet", "cyan", "amber", "rose", "blue"];
  return items.map((track, index) => ({
    id: track.id,
    title: track.title,
    artist: track.artist || "Unknown artist",
    album: track.album || "Unknown album",
    bpm: track.bpm ?? 0,
    key: track.musical_key || "--",
    genre: track.genre || "Uncategorised",
    duration: formatDuration(track.duration_seconds),
    added: new Date(`${track.discovered_at.replace(" ", "T")}Z`).toLocaleDateString(undefined, { day: "numeric", month: "short" }),
    rating: track.rating,
    color: track.color_tag || colors[index % colors.length],
    energy: energyLabel(track.energy_score),
    path: track.path,
    tags: track.tags ? track.tags.split(",") : [],
    fileSize: track.file_size,
    missing: track.missing === 1,
    addedAt: track.discovered_at,
    year: track.year,
    comment: track.comment,
    analysisStatus: track.analysis_status,
    analysisStrength: track.analysis_strength,
    lastPlayedAt: track.last_played_at,
    playCount: track.play_count,
    mood: track.mood,
    updatedAt: track.updated_at,
  }));
}

const previewTransferPlan: TransferPlan = {
  snapshot_id: 1,
  previous_snapshot_id: null,
  created_at: seedTimestamp,
  libraries: 1,
  crates: 3,
  tracks: 27,
  errors: 0,
  summary: { added: 2, modified: 1, unchanged: 0, removed: 0 },
  changes: [
    { crate_id: 1, source_path: "/Music/_Serato_/Subcrates/Wedding%%Dinner.crate", name: "Dinner", hierarchy_path: "Wedding%%Dinner", status: "modified", track_count: 12, matched_count: 12, added_tracks: 2, removed_tracks: 1, reordered: true, warnings: [] },
    { crate_id: 2, source_path: "/Music/_Serato_/Subcrates/Wedding%%Dancefloor.crate", name: "Dancefloor", hierarchy_path: "Wedding%%Dancefloor", status: "added", track_count: 9, matched_count: 9, added_tracks: 9, removed_tracks: 0, reordered: false, warnings: [] },
    { crate_id: 3, source_path: "/Music/_Serato_/Subcrates/Sunset.crate", name: "Sunset", hierarchy_path: "Sunset", status: "added", track_count: 6, matched_count: 5, added_tracks: 6, removed_tracks: 0, reordered: false, warnings: [{ code: "unmatched_tracks", severity: "warning", message: "1 track path is not indexed in Decksmith. Existing files are read directly during export." }] },
  ],
  metadata_coverage: { tracks: 26, bpm: 24, key: 23, comments: 8, ratings: 17, marker_tracks: 26, cue_tracks: 14, cue_points: 31, loop_records: 4, marker_failures: 0 },
  metadata_limits: [
    { field: "cue_points", status: "available", message: "31 cue points across 14 tracks are available. Slots D-H export as named memory cues under the published XML format." },
    { field: "saved_loops", status: "available", message: "Saved loops are transferred as Rekordbox memory loops when detected." },
  ],
};

function TransferWorkspace() {
  const [plan, setPlan] = useState<TransferPlan | null>(isDesktop() ? null : previewTransferPlan);
  const [selectedCrates, setSelectedCrates] = useState<Set<number>>(new Set(isDesktop() ? [] : [1, 2, 3]));
  const [history, setHistory] = useState<TransferExport[]>([]);
  const [reading, setReading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [notice, setNotice] = useState<{ title: string; detail: string; error?: boolean } | null>(null);
  const [lastExport, setLastExport] = useState<TransferExportResult | null>(null);

  useEffect(() => {
    if (!isDesktop()) return;
    Promise.all([
      invoke<TransferPlan | null>("load_transfer_plan"),
      invoke<TransferExport[]>("load_transfer_history"),
    ]).then(([nextPlan, exports]) => {
      setPlan(nextPlan);
      setHistory(exports);
      if (nextPlan) {
        setSelectedCrates(new Set(nextPlan.changes.filter((change) => change.crate_id !== null && (change.status === "added" || change.status === "modified")).map((change) => change.crate_id as number)));
      }
    }).catch((error) => setNotice({ title: "Transfer state could not be loaded", detail: String(error), error: true }));
  }, []);

  const currentChanges = plan?.changes.filter((change) => change.crate_id !== null && change.status !== "removed") ?? [];
  const selectedChanges = currentChanges.filter((change) => selectedCrates.has(change.crate_id as number));
  const selectedWarnings = selectedChanges.flatMap((change) => change.warnings);
  const validationErrors = selectedWarnings.filter((warning) => warning.severity === "error");
  const exportDisabled = exporting || reading || selectedCrates.size === 0 || validationErrors.length > 0;

  async function readSeratoChanges() {
    if (!isDesktop()) {
      setPlan(previewTransferPlan);
      setSelectedCrates(new Set([1, 2, 3]));
      setNotice({ title: "Serato comparison complete", detail: "3 changed crates are ready for review." });
      return;
    }
    setReading(true);
    setLastExport(null);
    setNotice({ title: "Reading Serato", detail: "Creating a read-only snapshot and comparing it with the previous one." });
    try {
      const nextPlan = await invoke<TransferPlan>("create_transfer_snapshot");
      setPlan(nextPlan);
      setSelectedCrates(new Set(nextPlan.changes.filter((change) => change.crate_id !== null && (change.status === "added" || change.status === "modified")).map((change) => change.crate_id as number)));
      setNotice({ title: "Comparison complete", detail: `${nextPlan.summary.added} added, ${nextPlan.summary.modified} modified, ${nextPlan.summary.removed} removed.` });
    } catch (error) {
      setNotice({ title: "Serato comparison failed", detail: String(error), error: true });
    } finally {
      setReading(false);
    }
  }

  async function exportTransfer() {
    if (exportDisabled) return;
    if (!isDesktop()) {
      const mock: TransferExportResult = { export_id: 1, destination_path: "/Exports/Decksmith Transfer", xml_path: "/Exports/Decksmith Transfer/decksmith-rekordbox.xml", report_path: "/Exports/Decksmith Transfer/transfer-report.json", manifest_path: "/Exports/Decksmith Transfer/transfer-manifest.json", crate_count: selectedCrates.size, track_count: selectedChanges.reduce((total, change) => total + change.track_count, 0), cue_count: 31, loop_count: 4, validation_status: "passed", warning_count: selectedWarnings.length, warnings: selectedWarnings };
      setLastExport(mock);
      setNotice({ title: "Transfer package created", detail: mock.destination_path });
      return;
    }
    const destination = await open({ directory: true, multiple: false, title: "Choose where Decksmith should create the transfer package" });
    if (!destination) return;
    setExporting(true);
    setNotice({ title: "Creating Rekordbox package", detail: "Writing a new XML file and validation report. Source libraries remain read-only." });
    try {
      const result = await invoke<TransferExportResult>("export_rekordbox_transfer", { destination, crateIds: Array.from(selectedCrates) });
      setLastExport(result);
      setHistory(await invoke<TransferExport[]>("load_transfer_history"));
      setNotice({ title: "Transfer package created", detail: result.destination_path });
    } catch (error) {
      setNotice({ title: "Transfer export failed", detail: String(error), error: true });
    } finally {
      setExporting(false);
    }
  }

  async function revealLastPackage() {
    if (!lastExport || handoffBusy) return;
    if (!isDesktop()) {
      setNotice({ title: "Package verified", detail: "The transfer folder is ready to reveal in the native app." });
      return;
    }
    setHandoffBusy(true);
    try {
      await invoke("reveal_transfer_package", { destination: lastExport.destination_path });
      setNotice({ title: "Package verified", detail: "The transfer folder was opened after its manifest passed verification." });
    } catch (error) {
      setNotice({ title: "Package verification failed", detail: String(error), error: true });
    } finally {
      setHandoffBusy(false);
    }
  }

  async function launchRekordboxHandoff() {
    if (!lastExport || handoffBusy) return;
    if (!isDesktop()) {
      setNotice({ title: "Rekordbox handoff ready", detail: "The native app verifies the package before launching Rekordbox." });
      return;
    }
    setHandoffBusy(true);
    try {
      await invoke("verify_transfer_package", { destination: lastExport.destination_path });
      await invoke("launch_rekordbox");
      setNotice({ title: "Rekordbox launched", detail: "Choose decksmith-rekordbox.xml as the Imported Library in Rekordbox preferences." });
    } catch (error) {
      setNotice({ title: "Rekordbox handoff failed", detail: String(error), error: true });
    } finally {
      setHandoffBusy(false);
    }
  }

  function toggleCrate(crateId: number) {
    setSelectedCrates((current) => {
      const next = new Set(current);
      if (next.has(crateId)) next.delete(crateId);
      else next.add(crateId);
      return next;
    });
  }

  return (
    <>
      <section className="transfer-workspace" aria-label="Transfer workspace">
        <aside className="transfer-source">
          <div className="transfer-pane-heading"><Database size={17} /><div><strong>Serato source</strong><span>Read-only library snapshot</span></div></div>
          <button className="transfer-read" disabled={reading || exporting} onClick={readSeratoChanges}><ArrowsClockwise size={16} /> {reading ? "Comparing..." : plan ? "Compare again" : "Read Serato"}</button>
          <dl className="transfer-source-stats">
            <div><dt>Libraries</dt><dd>{plan?.libraries ?? 0}</dd></div>
            <div><dt>Crates</dt><dd>{plan?.crates ?? 0}</dd></div>
            <div><dt>Tracks</dt><dd>{plan?.tracks ?? 0}</dd></div>
            <div><dt>Read errors</dt><dd className={plan?.errors ? "warning-text" : "success-text"}>{plan?.errors ?? 0}</dd></div>
          </dl>
          <section className="transfer-history">
            <h2>Transfer history</h2>
            {history.length === 0 ? <p>No packages created yet.</p> : history.slice(0, 4).map((item) => (
              <div key={item.id}><FileText size={14} /><span><strong>{item.crate_count} crates, {item.track_count} tracks</strong><small>{item.cue_count} cues, {item.loop_count} loops, validation {item.validation_status}</small><small>{item.created_at}</small></span></div>
            ))}
          </section>
          <div className="source-lock"><ShieldCheck size={17} weight="fill" /><span><strong>Source lock active</strong><small>Serato and audio files cannot be written by this workflow.</small></span></div>
        </aside>

        <section className="transfer-main">
          <header className="transfer-header">
            <div><span>Transfer plan</span><h1>Serato changes</h1><p>{plan ? `Compared with ${plan.previous_snapshot_id ? "the previous snapshot" : "the first snapshot"}. Select exactly what moves to Rekordbox.` : "Create a snapshot to identify changes before anything is exported."}</p></div>
            {plan && <time>{new Date(`${plan.created_at.replace(" ", "T")}Z`).toLocaleString()}</time>}
          </header>
          {notice && <div className={`transfer-notice ${notice.error ? "error" : ""}`}><span>{notice.error ? <Warning size={16} /> : <Check size={16} weight="bold" />}<strong>{notice.title}</strong><small>{notice.detail}</small></span><button onClick={() => setNotice(null)} aria-label="Dismiss transfer notice"><X size={14} /></button></div>}
          {plan ? (
            <>
              <div className="transfer-summary" aria-label="Change summary">
                {(["added", "modified", "unchanged", "removed"] as const).map((status) => <div key={status} className={status}><strong>{plan.summary[status]}</strong><span>{status}</span></div>)}
              </div>
              <div className="transfer-table-wrap">
                <table className="transfer-table">
                  <thead><tr><th className="transfer-check"><input type="checkbox" aria-label="Select all current crates" checked={currentChanges.length > 0 && currentChanges.every((change) => selectedCrates.has(change.crate_id as number))} onChange={(event) => setSelectedCrates(event.target.checked ? new Set(currentChanges.map((change) => change.crate_id as number)) : new Set())} /></th><th>Crate hierarchy</th><th>Status</th><th>Tracks</th><th>Change</th><th>Validation</th></tr></thead>
                  <tbody>{plan.changes.map((change) => (
                    <tr key={change.source_path} className={change.status === "removed" ? "removed" : ""}>
                      <td className="transfer-check">{change.crate_id !== null && change.status !== "removed" ? <input type="checkbox" checked={selectedCrates.has(change.crate_id)} onChange={() => toggleCrate(change.crate_id as number)} aria-label={`Select ${change.hierarchy_path.replaceAll("%%", " / ")}`} /> : null}</td>
                      <td><strong>{change.hierarchy_path.replaceAll("%%", " / ")}</strong><small>{change.matched_count}/{change.track_count} indexed</small></td>
                      <td><span className={`change-status ${change.status}`}>{change.status}</span></td>
                      <td className="mono-number">{change.track_count}</td>
                      <td><span className="change-detail">{change.reordered ? "Order changed" : change.status === "removed" ? `${change.removed_tracks} removed` : change.status === "unchanged" ? "No changes" : `+${change.added_tracks} / -${change.removed_tracks}`}</span></td>
                      <td>{change.warnings.length ? <span className={change.warnings.some((warning) => warning.severity === "error") ? "validation error" : "validation warning"}><Warning size={13} /> {change.warnings.length}</span> : <span className="validation clean"><Check size={13} /> Ready</span>}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="transfer-empty"><Database size={28} /><h2>No transfer snapshot</h2><p>Read Serato to create a safe baseline and identify changed crates.</p><button onClick={readSeratoChanges}>Read Serato</button></div>
          )}
        </section>

        <aside className="transfer-inspector">
          <div className="transfer-pane-heading"><ShieldCheck size={17} /><div><strong>Validation</strong><span>Metadata and safety report</span></div></div>
          <section className="transfer-selection"><span>Selected for export</span><strong>{selectedCrates.size} crates</strong><small>{selectedChanges.reduce((total, change) => total + change.track_count, 0)} playlist entries</small></section>
          <section className="coverage"><h2>Metadata coverage</h2>{plan ? (["bpm", "key", "comments", "ratings", "cue_points"] as const).map((field) => <div key={field}><span>{field.replaceAll("_", " ")}</span><strong>{field === "cue_points" ? plan.metadata_coverage[field] : `${plan.metadata_coverage[field]}/${plan.metadata_coverage.tracks}`}</strong></div>) : <p>Available after comparison.</p>}</section>
          <section className="transfer-warnings"><h2>Review before export</h2>{plan?.metadata_limits.map((limit) => <div className={limit.status} key={limit.field}>{limit.status === "available" ? <Check size={15} weight="bold" /> : <Warning size={15} />}<span><strong>{limit.field.replaceAll("_", " ")}</strong><small>{limit.message}</small></span></div>)}{selectedWarnings.map((warning, index) => <div className={warning.severity} key={`${warning.code}-${index}`}><Warning size={15} /><span><strong>{warning.code.replaceAll("_", " ")}</strong><small>{warning.message}</small></span></div>)}{plan && plan.metadata_limits.length === 0 && selectedWarnings.length === 0 ? <p>No warnings.</p> : null}</section>
          {lastExport && <section className="export-result"><Check size={18} weight="bold" /><span><strong>Package ready</strong><small>{lastExport.destination_path}</small><small>{lastExport.cue_count} cues, {lastExport.loop_count} loops, validation {lastExport.validation_status}</small><small>{lastExport.warning_count} warnings in transfer-report.json</small></span></section>}
        </aside>
      </section>
      <footer className="transfer-footer"><span><ShieldCheck size={16} weight="fill" /> Non-destructive export</span><small>{lastExport ? "Package manifest passed. Review the report before importing into Rekordbox." : "Creates a new XML package. Serato, Rekordbox and audio stay untouched."}</small>{lastExport ? <div className="transfer-footer-actions"><button className="secondary" disabled={handoffBusy} onClick={revealLastPackage}><FolderOpen size={15} /> Show package</button><button disabled={handoffBusy} onClick={launchRekordboxHandoff}>Open Rekordbox <ArrowRight size={15} /></button></div> : <button disabled={exportDisabled} onClick={exportTransfer}><UploadSimple size={16} /> {exporting ? "Creating package..." : "Create package"}<ArrowRight size={15} /></button>}</footer>
    </>
  );
}

function App() {
  const [workspaceMode, setWorkspaceMode] = useState<"library" | "transfer" | "forge" | "arrangement">("library");
  const [libraryTracks, setLibraryTracks] = useState<Track[]>(seedTracks);
  const [query, setQuery] = useState("");
  const [activeCrate, setActiveCrate] = useState("All tracks");
  const [selectedId, setSelectedId] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [view, setView] = useState<"list" | "grid">("list");
  const [filterOpen, setFilterOpen] = useState(false);
  const [importedNames, setImportedNames] = useState<string[]>([]);
  const [scanStatus, setScanStatus] = useState<{ message: string; detail: string; error?: boolean } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [scanProgress, setScanProgress] = useState<ScanProgressEvent | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState<AnalysisProgressEvent | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("title");
  const [sortAscending, setSortAscending] = useState(true);
  const [genreFilter, setGenreFilter] = useState("all");
  const [ratingFilter, setRatingFilter] = useState(0);
  const [bpmFilter, setBpmFilter] = useState("all");
  const [moodFilter, setMoodFilter] = useState("all");
  const [energyFilter, setEnergyFilter] = useState("all");
  const [managerOpen, setManagerOpen] = useState(false);
  const [folders, setFolders] = useState<MusicFolder[]>([]);
  const [issues, setIssues] = useState<LibraryIssues>({ missing: [], metadata_errors: [] });
  const [duplicates, setDuplicates] = useState<DuplicateGroup[] | null>(null);
  const [duplicateLoading, setDuplicateLoading] = useState(false);
  const [tagDraft, setTagDraft] = useState("");
  const [commentDraft, setCommentDraft] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [seratoCrates, setSeratoCrates] = useState<SeratoCrate[]>([]);
  const [activeCrateId, setActiveCrateId] = useState<number | null>(null);
  const [activeCrateTrackIds, setActiveCrateTrackIds] = useState<Set<number> | null>(null);
  const [seratoSyncing, setSeratoSyncing] = useState(false);
  const [waveforms, setWaveforms] = useState<Record<number, string>>({});
  const [artworks, setArtworks] = useState<Record<number, string | null>>({});
  const [selectedTrackIds, setSelectedTrackIds] = useState<Set<number>>(new Set());
  const [bulkTagDraft, setBulkTagDraft] = useState("");
  const [smartPlaylists, setSmartPlaylists] = useState<SmartPlaylist[]>([]);
  const [activeSmartPlaylistId, setActiveSmartPlaylistId] = useState<number | null>(null);
  const [activeSmartTrackIds, setActiveSmartTrackIds] = useState<Set<number> | null>(null);
  const [smartEditorOpen, setSmartEditorOpen] = useState(false);
  const [smartSaving, setSmartSaving] = useState(false);
  const [smartDraft, setSmartDraft] = useState({ name: "", genre: "", mood: "", energy: "any", minRating: 0, bpmMin: "", bpmMax: "", tag: "", history: "any" });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cacheState, setCacheState] = useState<CacheStatus | null>(null);
  const [cacheBusy, setCacheBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const playedSessionTracks = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!isDesktop()) return;
    invoke<CacheStatus>("prune_app_cache").then(setCacheState).catch(() => undefined);
    Promise.all([
      invoke<NativeTrack[]>("load_library_tracks"),
      invoke<SeratoCrate[]>("load_serato_crates"),
      invoke<SmartPlaylist[]>("load_smart_playlists"),
    ])
      .then(([items, crates, playlists]) => {
        setSeratoCrates(crates);
        setSmartPlaylists(playlists);
        if (items.length > 0) {
          const mapped = mapNativeTracks(items);
          setLibraryTracks(mapped);
          setSelectedId(mapped[0].id);
        }
      })
      .catch((error) => setScanStatus({ message: "Library could not be loaded", detail: String(error), error: true }));
  }, []);

  useEffect(() => {
    if (!isDesktop()) return;
    let disposed = false;
    let removeListener: (() => void) | undefined;
    listen<AnalysisProgressEvent>("analysis-progress", (event) => {
      if (!disposed) setAnalysisProgress(event.payload);
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
    const track = libraryTracks.find((item) => item.id === selectedId);
    setTagDraft(track?.tags?.join(", ") ?? "");
    setCommentDraft(track?.comment ?? "");
    setCurrentTime(0);
    setPlaying(false);
  }, [libraryTracks, selectedId]);

  useEffect(() => {
    if (!isDesktop()) return;
    let disposed = false;
    let removeListener: (() => void) | undefined;
    listen<ScanProgressEvent>("scan-progress", (event) => {
      if (!disposed) setScanProgress(event.payload);
    }).then((unlisten) => {
      if (disposed) unlisten();
      else removeListener = unlisten;
    });
    return () => {
      disposed = true;
      removeListener?.();
    };
  }, []);

  const tracks = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const genreCrates = new Set(["Afro House", "Amapiano"]);
    const filtered = libraryTracks.filter((track) => {
      if (normalized && ![track.title, track.artist, track.album, track.genre, track.mood ?? "", track.energy, track.comment ?? "", track.key, String(track.bpm), ...(track.tags ?? [])].some((value) => value.toLowerCase().includes(normalized))) return false;
      if (activeCrate === "Favourites" && track.rating === 0) return false;
      if (activeCrateId !== null && activeCrateTrackIds && !activeCrateTrackIds.has(track.id)) return false;
      if (activeSmartPlaylistId !== null && activeSmartTrackIds && !activeSmartTrackIds.has(track.id)) return false;
      if (activeCrate === "Recently added" && !isRecent(track.addedAt)) return false;
      if (activeCrate === "Recently modified" && !isRecent(track.updatedAt)) return false;
      if (activeCrate === "Recently played" && !isRecent(track.lastPlayedAt)) return false;
      if (activeCrateId === null && genreCrates.has(activeCrate) && track.genre !== activeCrate) return false;
      if (genreFilter !== "all" && track.genre !== genreFilter) return false;
      if (ratingFilter > 0 && track.rating < ratingFilter) return false;
      if (moodFilter !== "all" && track.mood !== moodFilter) return false;
      if (energyFilter !== "all" && track.energy.toLowerCase() !== energyFilter) return false;
      if (bpmFilter === "under-110" && track.bpm >= 110) return false;
      if (bpmFilter === "110-120" && (track.bpm < 110 || track.bpm > 120)) return false;
      if (bpmFilter === "over-120" && track.bpm <= 120) return false;
      return true;
    });
    return filtered.sort((a, b) => {
      const values: Record<SortKey, [string | number, string | number]> = {
        title: [a.title, b.title], artist: [a.artist, b.artist], bpm: [a.bpm, b.bpm],
        key: [a.key, b.key], genre: [a.genre, b.genre], duration: [a.duration, b.duration],
      };
      const [left, right] = values[sortKey];
      const result = typeof left === "number" && typeof right === "number" ? left - right : String(left).localeCompare(String(right));
      return sortAscending ? result : -result;
    });
  }, [activeCrate, activeCrateId, activeCrateTrackIds, activeSmartPlaylistId, activeSmartTrackIds, bpmFilter, energyFilter, genreFilter, libraryTracks, moodFilter, query, ratingFilter, sortAscending, sortKey]);

  const selected = libraryTracks.find((track) => track.id === selectedId) ?? libraryTracks[0] ?? seedTracks[0];
  const activeJobCount = Number(scanning) + Number(analysing);
  const allVisibleSelected = tracks.length > 0 && tracks.every((track) => selectedTrackIds.has(track.id));
  const someVisibleSelected = tracks.some((track) => selectedTrackIds.has(track.id));
  const smartHasRule = Boolean(smartDraft.genre || smartDraft.mood || smartDraft.energy !== "any" || smartDraft.minRating || smartDraft.bpmMin || smartDraft.bpmMax || smartDraft.tag.trim() || smartDraft.history !== "any");
  const genres = useMemo(() => Array.from(new Set(libraryTracks.map((track) => track.genre))).sort(), [libraryTracks]);
  const audioSource = selected.path && isDesktop() ? convertFileSrc(selected.path) : undefined;
  const waveformSource = waveforms[selected.id] && isDesktop() ? convertFileSrc(waveforms[selected.id]) : undefined;
  const artworkSource = artworks[selected.id] ?? undefined;

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someVisibleSelected && !allVisibleSelected;
  }, [allVisibleSelected, someVisibleSelected]);

  useEffect(() => {
    if (!isDesktop() || !selected.path || waveforms[selected.id]) return;
    let disposed = false;
    invoke<{ path: string }>("generate_track_waveform", { trackId: selected.id })
      .then((result) => {
        if (!disposed) setWaveforms((items) => ({ ...items, [selected.id]: result.path }));
      })
      .catch(() => undefined);
    return () => { disposed = true; };
  }, [selected.id, selected.path, waveforms]);

  useEffect(() => {
    if (!isDesktop() || !selected.path || Object.prototype.hasOwnProperty.call(artworks, selected.id)) return;
    let disposed = false;
    invoke<{ path: string | null }>("generate_track_artwork", { trackId: selected.id })
      .then((result) => {
        if (!disposed) setArtworks((items) => ({ ...items, [selected.id]: result.path ? convertFileSrc(result.path) : null }));
      })
      .catch(() => {
        if (!disposed) setArtworks((items) => ({ ...items, [selected.id]: null }));
      });
    return () => { disposed = true; };
  }, [artworks, selected.id, selected.path]);

  async function addMusic() {
    if (analysing) return;
    if (!isDesktop()) {
      fileInput.current?.click();
      return;
    }

    const folder = await open({ directory: true, multiple: false, title: "Choose a music folder" });
    if (!folder) return;

    await runFolderScan(folder);
  }

  async function runFolderScan(folder: string) {
    setScanning(true);
    setScanProgress(null);
    setJobsOpen(true);
    setScanStatus({ message: "Scanning music folder", detail: folder });
    try {
      const result = await invoke<ScanResult>("scan_music_folder", { folder });
      const indexed = await invoke<NativeTrack[]>("load_library_tracks");
      const mapped = mapNativeTracks(indexed);
      setLibraryTracks(mapped);
      if (mapped.length > 0) setSelectedId(mapped[0].id);
      await loadManagerData();
      setScanStatus(result.cancelled ? {
        message: "Music folder scan cancelled",
        detail: `${result.files_seen} audio files were checked. Existing library records were preserved.`,
      } : {
        message: `${result.tracks_added} tracks added, ${result.tracks_updated} updated`,
        detail: `${result.files_seen} audio files scanned. ${result.files_skipped} unchanged. ${result.errors} errors.`,
        error: result.errors > 0,
      });
    } catch (error) {
      setScanStatus({ message: "Music folder scan failed", detail: String(error), error: true });
    } finally {
      setScanning(false);
    }
  }

  async function loadManagerData() {
    if (!isDesktop()) return;
    try {
      const [nextFolders, nextIssues] = await Promise.all([
        invoke<MusicFolder[]>("load_music_folders"),
        invoke<LibraryIssues>("load_library_issues"),
      ]);
      setFolders(nextFolders);
      setIssues(nextIssues);
    } catch (error) {
      setScanStatus({ message: "Library status could not be loaded", detail: String(error), error: true });
    }
  }

  async function openManager() {
    setManagerOpen(true);
    await loadManagerData();
  }

  async function analyseDuplicates() {
    if (!isDesktop()) return;
    setDuplicateLoading(true);
    try {
      setDuplicates(await invoke<DuplicateGroup[]>("find_duplicate_tracks"));
    } catch (error) {
      setScanStatus({ message: "Duplicate analysis failed", detail: String(error), error: true });
    } finally {
      setDuplicateLoading(false);
    }
  }

  async function syncSerato() {
    if (!isDesktop()) return;
    setSeratoSyncing(true);
    setScanStatus({ message: "Reading Serato crates", detail: "Decksmith is reading crate files without modifying them." });
    try {
      const result = await invoke<{ libraries: number; crates: number; tracks: number; errors: number }>("sync_serato_library");
      setSeratoCrates(await invoke<SeratoCrate[]>("load_serato_crates"));
      setScanStatus({
        message: `${result.crates} Serato crates imported`,
        detail: `${result.tracks} ordered track references read from ${result.libraries} library. ${result.errors} errors.`,
        error: result.errors > 0,
      });
    } catch (error) {
      setScanStatus({ message: "Serato crates could not be imported", detail: String(error), error: true });
    } finally {
      setSeratoSyncing(false);
    }
  }

  async function selectSeratoCrate(crate: SeratoCrate) {
    setActiveCrate(crate.hierarchy_path.replaceAll("%%", " / "));
    setActiveCrateId(crate.id);
    setActiveSmartPlaylistId(null);
    setActiveSmartTrackIds(null);
    try {
      const ids = await invoke<number[]>("load_crate_tracks", { crateId: crate.id });
      setActiveCrateTrackIds(new Set(ids));
    } catch (error) {
      setScanStatus({ message: "Crate tracks could not be loaded", detail: String(error), error: true });
    }
  }

  function selectLibrarySection(name: string) {
    setActiveCrate(name);
    setActiveCrateId(null);
    setActiveCrateTrackIds(null);
    setActiveSmartPlaylistId(null);
    setActiveSmartTrackIds(null);
  }

  async function selectSmartPlaylist(playlist: SmartPlaylist) {
    setActiveCrate(playlist.name);
    setActiveCrateId(null);
    setActiveCrateTrackIds(null);
    setActiveSmartPlaylistId(playlist.id);
    try {
      const ids = await invoke<number[]>("load_smart_playlist_tracks", { playlistId: playlist.id });
      setActiveSmartTrackIds(new Set(ids));
    } catch (error) {
      setScanStatus({ message: "Smart playlist could not be loaded", detail: String(error), error: true });
    }
  }

  async function refreshSmartPlaylists() {
    if (!isDesktop()) return;
    setSmartPlaylists(await invoke<SmartPlaylist[]>("load_smart_playlists"));
    if (activeSmartPlaylistId !== null) {
      const ids = await invoke<number[]>("load_smart_playlist_tracks", { playlistId: activeSmartPlaylistId });
      setActiveSmartTrackIds(new Set(ids));
    }
  }

  async function createSmartPlaylist() {
    if (!isDesktop() || smartSaving) return;
    const rules: Record<string, string | number | boolean> = {};
    if (smartDraft.genre) rules.genre = smartDraft.genre;
    if (smartDraft.mood) rules.mood = smartDraft.mood;
    if (smartDraft.energy === "low") rules.energy_max = 0.31;
    if (smartDraft.energy === "warm") { rules.energy_min = 0.32; rules.energy_max = 0.54; }
    if (smartDraft.energy === "high") { rules.energy_min = 0.55; rules.energy_max = 0.77; }
    if (smartDraft.energy === "peak") rules.energy_min = 0.78;
    if (smartDraft.minRating) rules.min_rating = smartDraft.minRating;
    if (smartDraft.bpmMin) rules.bpm_min = Number(smartDraft.bpmMin);
    if (smartDraft.bpmMax) rules.bpm_max = Number(smartDraft.bpmMax);
    if (smartDraft.tag.trim()) rules.tag = smartDraft.tag.trim();
    if (smartDraft.history === "unplayed") rules.unplayed = true;
    if (smartDraft.history === "played-30") rules.played_within_days = 30;
    if (smartDraft.history === "added-30") rules.added_within_days = 30;
    setSmartSaving(true);
    try {
      const created = await invoke<SmartPlaylist>("create_smart_playlist", { name: smartDraft.name, rules });
      const playlists = await invoke<SmartPlaylist[]>("load_smart_playlists");
      setSmartPlaylists(playlists);
      setSmartEditorOpen(false);
      setSmartDraft({ name: "", genre: "", mood: "", energy: "any", minRating: 0, bpmMin: "", bpmMax: "", tag: "", history: "any" });
      await selectSmartPlaylist(created);
    } catch (error) {
      setScanStatus({ message: "Smart playlist could not be created", detail: String(error), error: true });
    } finally {
      setSmartSaving(false);
    }
  }

  async function removeSmartPlaylist(playlist: SmartPlaylist) {
    if (!isDesktop() || !window.confirm(`Delete smart playlist "${playlist.name}"?`)) return;
    try {
      await invoke("delete_smart_playlist", { playlistId: playlist.id });
      setSmartPlaylists(await invoke<SmartPlaylist[]>("load_smart_playlists"));
      if (activeSmartPlaylistId === playlist.id) selectLibrarySection("All tracks");
    } catch (error) {
      setScanStatus({ message: "Smart playlist could not be deleted", detail: String(error), error: true });
    }
  }

  function toggleTrackSelection(trackId: number, checked: boolean) {
    setSelectedTrackIds((current) => {
      const next = new Set(current);
      if (checked) next.add(trackId);
      else next.delete(trackId);
      return next;
    });
  }

  function toggleVisibleTracks() {
    const visibleIds = tracks.map((track) => track.id);
    const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedTrackIds.has(id));
    setSelectedTrackIds((current) => {
      const next = new Set(current);
      visibleIds.forEach((id) => allSelected ? next.delete(id) : next.add(id));
      return next;
    });
  }

  async function applyBulkMetadata(update: { rating?: number; tags?: string[]; colorTag?: string }) {
    if (!isDesktop() || selectedTrackIds.size === 0) return;
    try {
      await invoke("bulk_update_track_metadata", {
        trackIds: Array.from(selectedTrackIds),
        rating: update.rating ?? null,
        tags: update.tags ?? null,
        colorTag: update.colorTag ?? null,
        mood: null,
        tagMode: "add",
      });
      const indexed = await invoke<NativeTrack[]>("load_library_tracks");
      setLibraryTracks(mapNativeTracks(indexed));
      await refreshSmartPlaylists();
      setBulkTagDraft("");
      setScanStatus({ message: `${selectedTrackIds.size} tracks updated`, detail: "Bulk metadata was saved to Decksmith without modifying the audio files." });
    } catch (error) {
      setScanStatus({ message: "Bulk edit could not be saved", detail: String(error), error: true });
    }
  }

  function handleAudioPlay() {
    setPlaying(true);
    if (!isDesktop() || !selected.path || playedSessionTracks.current.has(selected.id)) return;
    playedSessionTracks.current.add(selected.id);
    invoke<{ last_played_at: string; play_count: number }>("record_track_playback", { trackId: selected.id })
      .then((result) => {
        setLibraryTracks((items) => items.map((track) => track.id === selected.id ? {
          ...track, lastPlayedAt: result.last_played_at, playCount: result.play_count,
        } : track));
        refreshSmartPlaylists().catch(() => undefined);
      })
      .catch((error) => setScanStatus({ message: "Play history could not be saved", detail: String(error), error: true }));
  }

  async function setTrackRating(trackId: number, rating: number) {
    setLibraryTracks((items) => items.map((item) => item.id === trackId ? { ...item, rating, updatedAt: currentSqliteTimestamp() } : item));
    if (!isDesktop()) return;
    try {
      await invoke("update_track_metadata", { trackId, rating, tags: null, colorTag: null, mood: null, comment: null });
      await refreshSmartPlaylists();
    } catch (error) {
      setScanStatus({ message: "Rating could not be saved", detail: String(error), error: true });
    }
  }

  async function saveTags() {
    const tags = tagDraft.split(",").map((tag) => tag.trim()).filter(Boolean);
    setLibraryTracks((items) => items.map((item) => item.id === selected.id ? { ...item, tags, updatedAt: currentSqliteTimestamp() } : item));
    if (!isDesktop()) return;
    try {
      await invoke("update_track_metadata", { trackId: selected.id, rating: null, tags, colorTag: null, mood: null, comment: null });
      await refreshSmartPlaylists();
    } catch (error) {
      setScanStatus({ message: "Tags could not be saved", detail: String(error), error: true });
    }
  }

  async function setTrackColor(color: string) {
    setLibraryTracks((items) => items.map((item) => item.id === selected.id ? { ...item, color, updatedAt: currentSqliteTimestamp() } : item));
    if (!isDesktop()) return;
    try {
      await invoke("update_track_metadata", { trackId: selected.id, rating: null, tags: null, colorTag: color, mood: null, comment: null });
      await refreshSmartPlaylists();
    } catch (error) {
      setScanStatus({ message: "Colour tag could not be saved", detail: String(error), error: true });
    }
  }

  async function setTrackMood(mood: string) {
    setLibraryTracks((items) => items.map((item) => item.id === selected.id ? { ...item, mood, updatedAt: currentSqliteTimestamp() } : item));
    if (!isDesktop()) return;
    try {
      await invoke("update_track_metadata", { trackId: selected.id, rating: null, tags: null, colorTag: null, mood, comment: null });
      await refreshSmartPlaylists();
    } catch (error) {
      setScanStatus({ message: "Mood could not be saved", detail: String(error), error: true });
    }
  }

  async function saveComment() {
    const comment = commentDraft.trim();
    if (comment === (selected.comment ?? "")) return;
    setCommentDraft(comment);
    setLibraryTracks((items) => items.map((item) => item.id === selected.id ? { ...item, comment, updatedAt: currentSqliteTimestamp() } : item));
    if (!isDesktop()) return;
    try {
      await invoke("update_track_metadata", { trackId: selected.id, rating: null, tags: null, colorTag: null, mood: null, comment });
    } catch (error) {
      setScanStatus({ message: "Comment could not be saved", detail: String(error), error: true });
    }
  }

  async function startAnalysis(trackIds?: number[], force = false) {
    if (!isDesktop() || analysing || scanning) return;
    setAnalysing(true);
    setAnalysisProgress(null);
    setJobsOpen(true);
    setScanStatus({
      message: trackIds?.length === 1 ? "Analysing selected track" : "Analysing library",
      detail: "Decksmith is reading audio locally to estimate BPM, musical key and signal energy.",
    });
    try {
      const result = await invoke<AnalysisResult>("analyse_library", { trackIds: trackIds ?? null, force });
      const indexed = await invoke<NativeTrack[]>("load_library_tracks");
      setLibraryTracks(mapNativeTracks(indexed));
      setScanStatus({
        message: result.cancelled ? "Audio analysis cancelled" : `${result.completed} tracks analysed`,
        detail: `${result.processed} of ${result.total} processed. ${result.failed} failed and remain visible for review.`,
        error: result.failed > 0,
      });
    } catch (error) {
      setScanStatus({ message: "Audio analysis failed", detail: String(error), error: true });
    } finally {
      setAnalysing(false);
    }
  }

  async function cancelAnalysis() {
    if (!isDesktop() || !analysing) return;
    try {
      await invoke<boolean>("cancel_audio_analysis");
      setScanStatus({ message: "Cancelling audio analysis", detail: "Decksmith will stop safely before the next track." });
    } catch (error) {
      setScanStatus({ message: "Could not cancel analysis", detail: String(error), error: true });
    }
  }

  function changeSort(next: SortKey) {
    if (sortKey === next) setSortAscending((value) => !value);
    else { setSortKey(next); setSortAscending(true); }
  }

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return null;
    return sortAscending ? <ArrowUp size={10} /> : <ArrowDown size={10} />;
  }

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio || !audio.src) return;
    if (audio.paused) await audio.play();
    else audio.pause();
  }

  function playTrack(trackId: number) {
    setSelectedId(trackId);
    window.setTimeout(() => audioRef.current?.play().catch(() => undefined), 0);
  }

  function selectAdjacent(direction: -1 | 1) {
    if (tracks.length === 0) return;
    const current = Math.max(0, tracks.findIndex((track) => track.id === selected.id));
    const next = (current + direction + tracks.length) % tracks.length;
    playTrack(tracks[next].id);
  }

  async function cancelScan() {
    if (!isDesktop() || !scanning) return;
    try {
      await invoke<boolean>("cancel_music_scan");
      setScanStatus({ message: "Cancelling scan", detail: "Decksmith will stop safely after the current file." });
    } catch (error) {
      setScanStatus({ message: "Could not cancel scan", detail: String(error), error: true });
    }
  }

  function onImport(files: FileList | null) {
    if (!files) return;
    const audio = Array.from(files).filter((file) => file.type.startsWith("audio/") || /\.(mp3|wav|aiff|aif|flac|m4a)$/i.test(file.name));
    setImportedNames(audio.slice(0, 3).map((file) => file.name));
  }

  async function openSettings() {
    setSettingsOpen(true);
    if (!isDesktop()) return;
    try {
      setCacheState(await invoke<CacheStatus>("load_cache_status"));
    } catch (error) {
      setScanStatus({ message: "Cache status could not be loaded", detail: String(error), error: true });
    }
  }

  async function cleanCache() {
    if (!isDesktop() || cacheBusy) return;
    setCacheBusy(true);
    try {
      setCacheState(await invoke<CacheStatus>("prune_app_cache"));
    } catch (error) {
      setScanStatus({ message: "Cache cleanup failed", detail: String(error), error: true });
    } finally {
      setCacheBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="titlebar">
        <div className="titlebar-drag-region" data-tauri-drag-region aria-hidden="true" />
        <div className="window-controls" aria-label="Window controls">
          <button className="window-close" aria-label="Close Decksmith" title="Close" onClick={() => void controlWindow("close")} />
          <button className="window-minimize" aria-label="Minimize Decksmith" title="Minimize" onClick={() => void controlWindow("minimize")} />
          <button className="window-maximize" aria-label="Maximize Decksmith" title="Maximize" onClick={() => void controlWindow("maximize")} />
        </div>
        {workspaceMode === "library" ? <button className="icon-button" aria-label="Toggle library sidebar" onClick={() => setSidebarOpen((value) => !value)}><SidebarSimple size={18} /></button> : <span className="titlebar-spacer" />}
        <div className="brand-mark"><Waveform size={19} weight="bold" /></div>
        <strong className="brand-name">Decksmith</strong>
        <nav className="workspace-switch" aria-label="Workspace">
          <button className={workspaceMode === "library" ? "active" : ""} onClick={() => setWorkspaceMode("library")}>Library</button>
          <button className={workspaceMode === "transfer" ? "active" : ""} onClick={() => setWorkspaceMode("transfer")}>Transfer</button>
          <button className={workspaceMode === "forge" ? "active" : ""} onClick={() => setWorkspaceMode("forge")}>Forge</button>
          <button className={workspaceMode === "arrangement" ? "active" : ""} onClick={() => setWorkspaceMode("arrangement")}>Arrangement</button>
        </nav>
        <div className="title-actions">
          {workspaceMode === "library" && <button className="quiet-button" onClick={() => setJobsOpen((value) => !value)}><Queue size={17} /> Jobs <span className="job-count">{activeJobCount}</span></button>}
          <button className="icon-button" aria-label="Settings" onClick={openSettings}><Gear size={18} /></button>
        </div>
      </header>

      {settingsOpen && <div className="settings-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSettingsOpen(false); }}>
        <section className="settings-dialog" role="dialog" aria-modal="true" aria-label="Decksmith settings">
          <header><div><span>Decksmith</span><h1>Settings</h1></div><button aria-label="Close settings" onClick={() => setSettingsOpen(false)}><X size={17} /></button></header>
          <section className="settings-cache"><div className="settings-section-heading"><div><span>Storage</span><h2>App-owned cache</h2></div><strong>{cacheState ? formatBytes(cacheState.total_bytes) : "Checking…"}</strong></div><p>Prepared audio, stems and artwork live here. Cleanup removes only unreferenced derivatives; projects and original music are never deleted.</p>{cacheState && <div className="cache-category-list">{Object.entries(cacheState.categories).map(([name, category]) => <div key={name}><span>{name.charAt(0).toUpperCase() + name.slice(1)}</span><strong>{formatBytes(category.bytes)}</strong><small>{category.files} files{category.reclaimable_bytes ? ` · ${formatBytes(category.reclaimable_bytes)} reclaimable` : " · clean"}</small></div>)}</div>}<div className="cache-clean-row"><div>{cacheState?.removed_bytes ? <><strong>{formatBytes(cacheState.removed_bytes)} reclaimed</strong><span>{cacheState.removed_files} unused files removed safely</span></> : <><strong>{cacheState?.reclaimable_bytes ? `${formatBytes(cacheState.reclaimable_bytes)} can be reclaimed` : "Cache is clean"}</strong><span>Decksmith also prunes known orphaned renders when it starts.</span></>}</div><button disabled={cacheBusy || !isDesktop()} onClick={cleanCache}>{cacheBusy ? "Cleaning…" : "Clean unused files"}</button></div></section>
          <section className="settings-safety"><ShieldCheck size={18} weight="fill" /><div><strong>Local-first and source-safe</strong><p>Decksmith reads your music library and keeps all analysis, drafts and projects on this Mac.</p></div></section>
        </section>
      </div>}

      {workspaceMode === "transfer" ? <TransferWorkspace /> : workspaceMode === "forge" ? <ForgeWorkspace tracks={libraryTracks} initialTrackId={selectedId} onOpenArrangement={() => setWorkspaceMode("arrangement")} /> : workspaceMode === "arrangement" ? <ArrangementWorkspace tracks={libraryTracks} /> : <>
      {jobsOpen && (
        <aside className="jobs-popover" aria-label="Background jobs">
          <div className="jobs-heading"><div><strong>Background jobs</strong><span>{activeJobCount ? `${activeJobCount} running` : "All caught up"}</span></div><button className="icon-button" onClick={() => setJobsOpen(false)} aria-label="Close jobs"><X size={15} /></button></div>
          {scanning && (
            <div className="job-item running">
              <div className="job-icon"><Waveform size={18} /></div>
              <div className="job-copy"><strong>Scanning music folder</strong><span>{scanProgress?.current_file ?? "Preparing scanner..."}</span><small>{scanProgress?.data.files_seen ?? 0} files checked&nbsp;&nbsp; {scanProgress?.data.tracks_added ?? 0} added&nbsp;&nbsp; {scanProgress?.data.errors ?? 0} errors</small></div>
              <button className="cancel-job" onClick={cancelScan}>Cancel</button>
            </div>
          )}
          {analysing && (
            <div className="job-item running">
              <div className="job-icon"><Sparkle size={18} weight="fill" /></div>
              <div className="job-copy"><strong>Audio analysis</strong><span>{analysisProgress?.data.current_file || "Preparing analysis..."}</span><small>{analysisProgress?.data.processed ?? 0}/{analysisProgress?.data.total ?? libraryTracks.length} processed&nbsp;&nbsp; {analysisProgress?.data.completed ?? 0} complete&nbsp;&nbsp; {analysisProgress?.data.failed ?? 0} failed</small></div>
              <button className="cancel-job" onClick={cancelAnalysis}>Cancel</button>
            </div>
          )}
          {!scanning && !analysing && analysisProgress?.event === "complete" ? (
            <div className="job-item"><div className="job-icon complete"><Check size={17} weight="bold" /></div><div className="job-copy"><strong>{analysisProgress.data.cancelled ? "Analysis cancelled" : "Audio analysis complete"}</strong><span>{analysisProgress.data.processed} of {analysisProgress.data.total} processed</span><small>{analysisProgress.data.completed} complete&nbsp;&nbsp; {analysisProgress.data.failed} failed</small></div></div>
          ) : !scanning && !analysing && scanProgress?.event === "complete" ? (
            <div className="job-item"><div className="job-icon complete"><Check size={17} weight="bold" /></div><div className="job-copy"><strong>{scanProgress.data.cancelled ? "Scan cancelled" : "Library scan complete"}</strong><span>{scanProgress.data.files_seen} files checked</span><small>{scanProgress.data.tracks_added} added&nbsp;&nbsp; {scanProgress.data.tracks_updated} updated</small></div></div>
          ) : !scanning && !analysing ? (
            <div className="jobs-empty"><Check size={20} /><span>No background work is running.</span></div>
          ) : null}
        </aside>
      )}

      {smartEditorOpen && (
        <aside className="smart-editor" aria-label="Create smart playlist">
          <div className="jobs-heading"><div><strong>New smart playlist</strong><span>Tracks update automatically as metadata changes</span></div><button className="icon-button" onClick={() => setSmartEditorOpen(false)} aria-label="Close smart playlist editor"><X size={15} /></button></div>
          <div className="smart-form">
            <label><span>Name</span><input value={smartDraft.name} onChange={(event) => setSmartDraft((draft) => ({ ...draft, name: event.target.value }))} placeholder="Late-night favourites" /></label>
            <div className="smart-form-grid">
              <label><span>Genre</span><select value={smartDraft.genre} onChange={(event) => setSmartDraft((draft) => ({ ...draft, genre: event.target.value }))}><option value="">Any genre</option>{genres.map((genre) => <option key={genre}>{genre}</option>)}</select></label>
              <label><span>Mood</span><select value={smartDraft.mood} onChange={(event) => setSmartDraft((draft) => ({ ...draft, mood: event.target.value }))}><option value="">Any mood</option>{moodOptions.map((mood) => <option key={mood}>{mood}</option>)}</select></label>
              <label><span>Energy</span><select value={smartDraft.energy} onChange={(event) => setSmartDraft((draft) => ({ ...draft, energy: event.target.value }))}><option value="any">Any energy</option><option value="low">Low</option><option value="warm">Warm</option><option value="high">High</option><option value="peak">Peak</option></select></label>
              <label><span>Minimum rating</span><select value={smartDraft.minRating} onChange={(event) => setSmartDraft((draft) => ({ ...draft, minRating: Number(event.target.value) }))}><option value="0">Any rating</option><option value="3">3+ stars</option><option value="4">4+ stars</option><option value="5">5 stars</option></select></label>
              <label><span>Minimum BPM</span><input inputMode="decimal" value={smartDraft.bpmMin} onChange={(event) => setSmartDraft((draft) => ({ ...draft, bpmMin: event.target.value }))} placeholder="90" /></label>
              <label><span>Maximum BPM</span><input inputMode="decimal" value={smartDraft.bpmMax} onChange={(event) => setSmartDraft((draft) => ({ ...draft, bpmMax: event.target.value }))} placeholder="125" /></label>
            </div>
            <label><span>Required tag</span><input value={smartDraft.tag} onChange={(event) => setSmartDraft((draft) => ({ ...draft, tag: event.target.value }))} placeholder="opener" /></label>
            <label><span>History</span><select value={smartDraft.history} onChange={(event) => setSmartDraft((draft) => ({ ...draft, history: event.target.value }))}><option value="any">Any play history</option><option value="unplayed">Never previewed</option><option value="played-30">Played in the last 30 days</option><option value="added-30">Added in the last 30 days</option></select></label>
            <button className="smart-save" disabled={smartSaving || !smartDraft.name.trim() || !smartHasRule} onClick={createSmartPlaylist}><ListPlus size={15} /> {smartSaving ? "Saving..." : "Create playlist"}</button>
          </div>
        </aside>
      )}

      {managerOpen && (
        <aside className="manager-popover" aria-label="Library management">
          <div className="jobs-heading"><div><strong>Library management</strong><span>Folders, file health and duplicates</span></div><button className="icon-button" onClick={() => setManagerOpen(false)} aria-label="Close library management"><X size={15} /></button></div>
          <section className="manager-section">
            <div className="manager-title"><strong>Music folders</strong><button onClick={addMusic}><Plus size={13} /> Add folder</button></div>
            {folders.length === 0 ? <p className="manager-empty">No native music folders have been indexed yet.</p> : folders.map((folder) => (
              <div className="folder-row" key={folder.id}><Folder size={17} /><div><strong>{folder.path.split("/").pop()}</strong><span>{folder.path}</span><small>{folder.track_count} tracks&nbsp;&nbsp; {folder.missing_count} missing</small></div><button disabled={scanning} onClick={() => runFolderScan(folder.path)}><ArrowsClockwise size={14} /> Rescan</button></div>
            ))}
          </section>
          <section className="manager-section issue-summary">
            <div><Warning size={17} /><span><strong>{issues.missing.length}</strong> missing files</span></div>
            <div><Warning size={17} /><span><strong>{issues.metadata_errors.length}</strong> metadata errors</span></div>
          </section>
          {(issues.missing.length > 0 || issues.metadata_errors.length > 0) && <div className="issue-list">{[...issues.missing, ...issues.metadata_errors].slice(0, 5).map((issue) => <div key={`${"metadata_error" in issue ? "e" : "m"}-${issue.id}`}><strong>{issue.title}</strong><span>{issue.artist || issue.path}</span></div>)}</div>}
          <section className="manager-section">
            <div className="manager-title"><strong>Duplicate audio</strong><button disabled={duplicateLoading} onClick={analyseDuplicates}><Copy size={13} /> {duplicateLoading ? "Analysing..." : "Analyse"}</button></div>
            {duplicates === null ? <p className="manager-empty">Analysis hashes size-matched files to prevent false matches.</p> : duplicates.length === 0 ? <p className="manager-empty success">No byte-identical duplicates found.</p> : <div className="duplicate-list">{duplicates.map((group) => <div key={group.hash}><strong>{group.tracks.length} identical files</strong>{group.tracks.map((track) => <span key={track.id}>{track.title} - {track.path}</span>)}</div>)}</div>}
          </section>
        </aside>
      )}

      <section className={`workspace ${sidebarOpen ? "" : "sidebar-collapsed"} ${inspectorOpen ? "" : "inspector-collapsed"}`}>
        <aside className="sidebar">
          <button className="import-button" disabled={scanning || analysing} onClick={addMusic}>{scanning ? <Waveform size={17} /> : <Plus size={17} weight="bold" />} {scanning ? "Scanning..." : analysing ? "Analysis running" : "Add music"}</button>
          <input ref={fileInput} className="sr-only" type="file" multiple accept="audio/*,.aiff,.aif,.flac" onChange={(event) => onImport(event.target.files)} />

          <nav className="library-nav" aria-label="Library">
            <p className="nav-label">Library</p>
            {crates.map(({ name, count, icon: Icon }) => {
              const liveCount = name === "All tracks" ? libraryTracks.length
                : name === "Favourites" ? libraryTracks.filter((track) => track.rating > 0).length
                : name === "Recently added" ? libraryTracks.filter((track) => isRecent(track.addedAt)).length
                : name === "Recently modified" ? libraryTracks.filter((track) => isRecent(track.updatedAt)).length
                : name === "Recently played" ? libraryTracks.filter((track) => isRecent(track.lastPlayedAt)).length
                : count;
              return (
              <button key={name} className={activeCrate === name && activeCrateId === null && activeSmartPlaylistId === null ? "active" : ""} onClick={() => selectLibrarySection(name)}>
                <Icon size={17} /><span>{name}</span><small>{liveCount.toLocaleString()}</small>
              </button>
              );
            })}

            <div className="nav-heading"><p className="nav-label">Smart playlists</p><button aria-label="Create smart playlist" onClick={() => setSmartEditorOpen(true)}><Plus size={15} /></button></div>
            {smartPlaylists.length === 0 ? <p className="nav-empty">No smart playlists</p> : smartPlaylists.map((playlist) => (
              <div className="smart-nav-row" key={playlist.id}>
                <button className={activeSmartPlaylistId === playlist.id ? "active" : ""} onClick={() => selectSmartPlaylist(playlist)}><SlidersHorizontal size={15} /><span>{playlist.name}</span><small>{playlist.track_count}</small></button>
                <button className="smart-delete" aria-label={`Delete ${playlist.name}`} onClick={() => removeSmartPlaylist(playlist)}><Trash size={13} /></button>
              </div>
            ))}

            <div className="nav-heading"><p className="nav-label">Crates</p><button aria-label="Add crate"><Plus size={15} /></button></div>
            {seratoCrates.length > 0 ? seratoCrates.map((crate, index) => {
              const depth = crate.hierarchy_path.split("%%").length - 1;
              const colors = ["violet", "cyan", "amber", "rose", "blue"];
              return <button key={crate.id} style={{ paddingLeft: 8 + depth * 12 }} className={activeCrateId === crate.id ? "active" : ""} onClick={() => selectSeratoCrate(crate)}><i className={`crate-color ${colors[index % colors.length]}`} /><span>{crate.name}</span><small>{crate.matched_count}/{crate.track_count}</small></button>;
            }) : playlists.map((playlist) => (
              <button key={playlist.name} className={activeCrate === playlist.name ? "active" : ""} onClick={() => selectLibrarySection(playlist.name)}>
                <i className={`crate-color ${playlist.color}`} /><span>{playlist.name}</span><small>{playlist.count}</small>
              </button>
            ))}
          </nav>

          <div className="sidebar-footer">
            <button onClick={openManager}><FolderOpen size={17} /><span>Music folders</span><small>{folders.length || ""}</small></button>
            <button disabled={seratoSyncing} onClick={syncSerato}><Shuffle size={17} /><span>{seratoSyncing ? "Reading Serato..." : "Serato library"}</span><small>{seratoCrates.length > 0 ? `${seratoCrates.length} crates` : "Found"}</small></button>
          </div>
        </aside>

        <section className="library-panel">
          <div className="library-toolbar">
            <div>
              <div className="breadcrumb"><span>Library</span><CaretRight size={12} /><span>{activeCrate}</span></div>
              <h1>{activeCrate}</h1>
            </div>
            <div className="toolbar-actions">
              <button className="tool-button analyse-button" disabled={analysing || scanning || libraryTracks.length === 0} onClick={() => startAnalysis()}><Sparkle size={16} weight="fill" /> {analysing ? "Analysing..." : "Analyse missing"}</button>
              <label className="search-box"><MagnifyingGlass size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, artist, genre, BPM..." aria-label="Search library" />{query && <button onClick={() => setQuery("")} aria-label="Clear search"><X size={14} /></button>}<kbd>⌘ K</kbd></label>
              <button className={filterOpen ? "tool-button active" : "tool-button"} onClick={() => setFilterOpen((value) => !value)}><SlidersHorizontal size={17} /> Filter</button>
              <div className="view-toggle" aria-label="View style">
                <button className={view === "list" ? "active" : ""} onClick={() => setView("list")} aria-label="List view"><ListBullets size={17} /></button>
                <button className={view === "grid" ? "active" : ""} onClick={() => setView("grid")} aria-label="Grid view"><GridFour size={17} /></button>
              </div>
            </div>
          </div>

          {filterOpen && (
            <div className="filter-strip">
              <label>Genre<select value={genreFilter} onChange={(event) => setGenreFilter(event.target.value)}><option value="all">All genres</option>{genres.map((genre) => <option key={genre}>{genre}</option>)}</select></label>
              <label>BPM<select value={bpmFilter} onChange={(event) => setBpmFilter(event.target.value)}><option value="all">Any tempo</option><option value="under-110">Under 110</option><option value="110-120">110-120</option><option value="over-120">Over 120</option></select></label>
              <label>Mood<select value={moodFilter} onChange={(event) => setMoodFilter(event.target.value)}><option value="all">Any mood</option>{moodOptions.map((mood) => <option key={mood}>{mood}</option>)}</select></label>
              <label>Energy<select value={energyFilter} onChange={(event) => setEnergyFilter(event.target.value)}><option value="all">Any energy</option><option value="low">Low</option><option value="warm">Warm</option><option value="high">High</option><option value="peak">Peak</option></select></label>
              <label>Rating<select value={ratingFilter} onChange={(event) => setRatingFilter(Number(event.target.value))}><option value="0">Any rating</option><option value="3">3+ stars</option><option value="4">4+ stars</option><option value="5">5 stars</option></select></label>
              <button className="clear-filters" onClick={() => { setGenreFilter("all"); setBpmFilter("all"); setMoodFilter("all"); setEnergyFilter("all"); setRatingFilter(0); }}>Clear</button><span>{tracks.length} matches</span>
            </div>
          )}

          {importedNames.length > 0 && (
            <div className="import-status"><span><Check size={15} weight="bold" /> {importedNames.length} audio files queued for analysis</span><small>{importedNames.join(", ")}</small><button onClick={() => setImportedNames([])} aria-label="Dismiss"><X size={14} /></button></div>
          )}

          {scanStatus && (
            <div className={`import-status ${scanStatus.error ? "error" : ""}`}><span>{scanStatus.error ? <X size={15} weight="bold" /> : <Check size={15} weight="bold" />} {scanStatus.message}</span><small>{scanStatus.detail}</small><button onClick={() => setScanStatus(null)} aria-label="Dismiss"><X size={14} /></button></div>
          )}

          {selectedTrackIds.size > 0 && (
            <div className="bulk-bar">
              <strong>{selectedTrackIds.size} selected</strong>
              <label>Rating<select defaultValue="" onChange={(event) => { if (event.target.value) applyBulkMetadata({ rating: Number(event.target.value) }); event.target.value = ""; }}><option value="" disabled>Set rating</option><option value="0">No rating</option><option value="3">3 stars</option><option value="4">4 stars</option><option value="5">5 stars</option></select></label>
              <div className="bulk-colours" aria-label="Set colour">{["violet", "cyan", "amber", "rose", "blue"].map((color) => <button key={color} className={color} onClick={() => applyBulkMetadata({ colorTag: color })} aria-label={`Set ${color} colour`} />)}</div>
              <label className="bulk-tag"><Tag size={13} /><input value={bulkTagDraft} onChange={(event) => setBulkTagDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && bulkTagDraft.trim()) applyBulkMetadata({ tags: bulkTagDraft.split(",").map((tag) => tag.trim()).filter(Boolean) }); }} placeholder="Add tags" /></label>
              <button className="bulk-apply" disabled={!bulkTagDraft.trim()} onClick={() => applyBulkMetadata({ tags: bulkTagDraft.split(",").map((tag) => tag.trim()).filter(Boolean) })}>Add</button>
              <button className="bulk-clear" onClick={() => setSelectedTrackIds(new Set())}>Clear selection</button>
            </div>
          )}

          <div className="table-wrap">
            {view === "list" ? (
              <table className="track-table">
                <thead><tr><th className="selection-col"><input ref={selectAllRef} type="checkbox" checked={allVisibleSelected} onChange={toggleVisibleTracks} aria-label="Select all visible tracks" /></th><th className="number-col">#</th><th><button onClick={() => changeSort("title")}>Title {sortIcon("title")}</button></th><th>Album</th><th className="compact-col"><button onClick={() => changeSort("bpm")}>BPM {sortIcon("bpm")}</button></th><th className="compact-col"><button onClick={() => changeSort("key")}>Key {sortIcon("key")}</button></th><th><button onClick={() => changeSort("genre")}>Genre {sortIcon("genre")}</button></th><th className="compact-col">Rating</th><th className="duration-col"><button onClick={() => changeSort("duration")}>Time {sortIcon("duration")}</button></th><th className="menu-col" /></tr></thead>
                <tbody>
                  {tracks.map((track, index) => (
                    <tr key={track.id} className={selectedId === track.id ? "selected" : ""} onClick={() => setSelectedId(track.id)} onDoubleClick={() => playTrack(track.id)}>
                      <td className="selection-col"><input type="checkbox" checked={selectedTrackIds.has(track.id)} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleTrackSelection(track.id, event.target.checked)} aria-label={`Select ${track.title}`} /></td>
                      <td className="number-col"><span className="row-number">{index + 1}</span><button className="row-play" aria-label={`Play ${track.title}`} onClick={(event) => { event.stopPropagation(); playTrack(track.id); }}><Play size={12} weight="fill" /></button></td>
                      <td><div className="track-title-cell"><div className={`artwork art-${track.color}`}>{artworks[track.id] ? <img src={artworks[track.id] ?? undefined} alt="" /> : <Waveform size={18} />}</div><span><strong>{track.title}</strong><small>{track.artist}</small></span></div></td>
                      <td className="muted-cell">{track.album}</td><td className="mono">{track.bpm || "--"}</td><td><span className="key-tag">{track.key}</span></td><td className="muted-cell">{track.genre}</td>
                      <td><div className="stars" aria-label={`${track.rating} stars`}>{[1, 2, 3, 4, 5].map((star) => <button key={star} aria-label={`Rate ${star} stars`} onClick={(event) => { event.stopPropagation(); setTrackRating(track.id, track.rating === star ? 0 : star); }}><Star size={12} weight={star <= track.rating ? "fill" : "regular"} /></button>)}</div></td>
                      <td className="mono muted-cell">{track.duration}</td><td><button className="row-menu" aria-label="Track actions"><DotsThree size={18} weight="bold" /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="track-grid">{tracks.map((track) => <div key={track.id} role="button" tabIndex={0} className={selectedId === track.id ? "track-card selected" : "track-card"} onClick={() => setSelectedId(track.id)} onKeyDown={(event) => { if (event.key === "Enter") setSelectedId(track.id); }}><input className="grid-select" type="checkbox" checked={selectedTrackIds.has(track.id)} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleTrackSelection(track.id, event.target.checked)} aria-label={`Select ${track.title}`} /><div className={`grid-art art-${track.color}`}>{artworks[track.id] ? <img src={artworks[track.id] ?? undefined} alt="" /> : <WaveformBars color={track.color} />}<Play size={24} weight="fill" /></div><strong>{track.title}</strong><span>{track.artist}</span><small>{track.bpm ? `${track.bpm} BPM` : "BPM pending"}&nbsp;&nbsp; {track.key}</small></div>)}</div>
            )}
            {tracks.length === 0 && <div className="empty-state"><MagnifyingGlass size={28} /><h2>No tracks found</h2><p>Try a different title, artist, genre, BPM or key.</p><button onClick={() => setQuery("")}>Clear search</button></div>}
          </div>
          <footer className="library-status"><span>{tracks.length} shown</span><span>{libraryTracks.length.toLocaleString()} tracks</span><span className="status-right"><i /> {scanning ? "Scanning library" : "Library indexed"}</span></footer>
        </section>

        <aside className="inspector">
          <div className="inspector-heading"><span>Track details</span><button className="icon-button" aria-label="Close inspector" onClick={() => setInspectorOpen(false)}><X size={16} /></button></div>
          <div className={`large-art art-${selected.color}`}>{artworkSource ? <img src={artworkSource} alt={`Cover artwork for ${selected.title}`} /> : <WaveformBars color={selected.color} />}<button aria-label={`Play ${selected.title}`} onClick={togglePlayback}>{playing ? <Pause size={24} weight="fill" /> : <Play size={24} weight="fill" />}</button></div>
          <div className="selected-copy"><h2>{selected.title}</h2><p>{selected.artist}</p></div>
          <div className="analysis-grid"><div><span>BPM</span><strong>{selected.bpm ? `${selected.bpm.toFixed(2)}` : "Pending"}</strong></div><div><span>Key</span><strong>{selected.key}</strong></div><div><span>Energy</span><strong>{selected.energy}</strong></div><div><span>Confidence</span><strong>{selected.analysisStrength != null ? `${Math.round(selected.analysisStrength * 100)}%` : "Pending"}</strong></div></div>
          <button className="track-analysis-button" disabled={analysing || scanning || !selected.path} onClick={() => startAnalysis([selected.id], selected.analysisStatus === "completed")}><Sparkle size={14} weight="fill" /> {selected.analysisStatus === "completed" ? "Re-analyse track" : selected.analysisStatus === "failed" ? "Retry analysis" : "Analyse track"}</button>
          <div className="waveform-preview">{waveformSource ? <img src={waveformSource} alt={`Waveform for ${selected.title}`} /> : <WaveformBars color={selected.color} />}<i className="preview-position" style={{ left: `${audioRef.current?.duration ? (currentTime / audioRef.current.duration) * 100 : 0}%` }} /></div>
          <section className="metadata"><h3>Metadata</h3><dl><div><dt>Album</dt><dd>{selected.album}</dd></div><div><dt>Genre</dt><dd>{selected.genre}</dd></div><div><dt>Year</dt><dd>{selected.year || "--"}</dd></div><div><dt>Duration</dt><dd>{selected.duration}</dd></div><div><dt>Added</dt><dd>{selected.added}</dd></div><div><dt>Previewed</dt><dd>{selected.playCount ? `${selected.playCount} time${selected.playCount === 1 ? "" : "s"}` : "Never"}</dd></div><div><dt>Last played</dt><dd>{selected.lastPlayedAt ? new Date(`${selected.lastPlayedAt.replace(" ", "T")}Z`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "Never"}</dd></div></dl></section>
          <section className="mood-editor"><label><span>Mood</span><select value={selected.mood ?? ""} onChange={(event) => setTrackMood(event.target.value)} aria-label="Mood"><option value="">No mood</option>{moodOptions.map((mood) => <option key={mood}>{mood}</option>)}</select></label></section>
          <section className="tag-editor"><h3>Tags</h3><input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} onBlur={saveTags} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} placeholder="sunset, warm, opener" /><small>Separate tags with commas</small></section>
          <section className="comment-editor"><label><span>Comment</span><textarea value={commentDraft} maxLength={4000} onChange={(event) => setCommentDraft(event.target.value)} onBlur={saveComment} placeholder="Mix notes, cue reminders or context" /></label><small>Saved in Decksmith without changing the audio file</small></section>
          <section className="colour-editor"><h3>Colour</h3><div>{["violet", "cyan", "amber", "rose", "blue"].map((color) => <button key={color} className={`${color} ${selected.color === color ? "active" : ""}`} onClick={() => setTrackColor(color)} aria-label={`Set ${color} colour`} />)}</div></section>
          <button className="forge-button" onClick={() => setWorkspaceMode("forge")}><Sparkle size={17} weight="fill" /> Start a mashup draft</button>
        </aside>

        {!inspectorOpen && <button className="open-inspector" onClick={() => setInspectorOpen(true)} aria-label="Open inspector"><SidebarSimple size={18} /></button>}
      </section>

      <footer className="transport">
        <audio ref={audioRef} src={audioSource} onPlay={handleAudioPlay} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} />
        <div className="now-playing"><div className={`transport-art art-${selected.color}`}>{artworkSource ? <img src={artworkSource} alt="" /> : <Waveform size={16} />}</div><div><strong>{selected.title}</strong><span>{selected.artist}</span></div><button aria-label="Favourite"><Heart size={17} /></button></div>
        <div className="transport-centre"><div className="transport-buttons"><button aria-label="Previous" onClick={() => selectAdjacent(-1)}><SkipBack size={17} weight="fill" /></button><button className="main-play" aria-label={playing ? "Pause" : "Play"} onClick={togglePlayback}>{playing ? <Pause size={19} weight="fill" /> : <Play size={19} weight="fill" />}</button><button aria-label="Next" onClick={() => selectAdjacent(1)}><SkipForward size={17} weight="fill" /></button></div><div className="progress-row"><span>{formatDuration(currentTime)}</span><button className="progress" aria-label="Seek audio" onClick={(event) => { const audio = audioRef.current; if (!audio || !audio.duration) return; const rect = event.currentTarget.getBoundingClientRect(); audio.currentTime = ((event.clientX - rect.left) / rect.width) * audio.duration; }}><i style={{ right: `${100 - (audioRef.current?.duration ? (currentTime / audioRef.current.duration) * 100 : 0)}%` }} /></button><span>{selected.duration}</span></div></div>
        <div className="transport-tools"><span className="tempo-chip">{selected.bpm ? `${selected.bpm} BPM` : "BPM pending"}</span><span className="tempo-chip">{selected.key}</span><button aria-label="Headphone cue"><Headphones size={18} /></button><button aria-label="Queue"><SquaresFour size={18} /></button><button aria-label="Sort"><ArrowsDownUp size={18} /></button></div>
      </footer>
      </>}
    </main>
  );
}

export default App;
