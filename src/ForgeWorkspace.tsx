import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  ArrowRight,
  CheckCircle,
  Gauge,
  ListNumbers,
  MusicNotes,
  Sparkle,
  Warning,
} from "@phosphor-icons/react";

export type ForgeTrack = {
  id: number;
  title: string;
  artist: string;
  genre: string;
  bpm: number;
  key: string;
  duration: string;
  energy: string;
  rating: number;
  tags?: string[];
};

type NativeSuggestionTrack = {
  id: number;
  title: string;
  artist: string;
  genre: string;
  bpm: number | null;
  musical_key: string;
};

type Match = {
  track: NativeSuggestionTrack;
  score: number;
  suggested_tempo: number | null;
  suggested_pitch_semitones: number;
  explanations: string[];
  components: Record<"tempo" | "key" | "energy" | "groove", number>;
};

type MatchPayload = { anchor: NativeSuggestionTrack; suggestions: Match[] };

type DraftTrack = {
  track_id: number;
  title: string;
  artist: string;
  position: number;
  role: string;
  compatibility_score: number;
  suggested_tempo: number | null;
  suggested_pitch_semitones: number | null;
  explanations: string[];
};

type AssistantDraft = {
  id: number;
  draft_kind: "mashup" | "setlist";
  name: string;
  status: "idea" | "ready" | "needs_review" | "finished";
  project_id: number | null;
  brief: {
    compatibility_score?: number;
    working_tempo?: number | null;
    duration_minutes?: number;
    estimated_duration_seconds?: number;
    energy_curve?: string;
    genre?: string;
  };
  tracks: DraftTrack[];
  updated_at: string;
};

function isDesktop() {
  return "__TAURI_INTERNALS__" in window;
}

function previewMatches(tracks: ForgeTrack[], anchorId: number): MatchPayload {
  const anchor = tracks.find((track) => track.id === anchorId) ?? tracks[0];
  const suggestions = tracks
    .filter((track) => track.id !== anchor.id)
    .map((track) => {
      const bpmDelta = Math.abs((track.bpm || 120) - (anchor.bpm || 120));
      const score = Math.max(48, Math.round(94 - bpmDelta * 3 - (track.genre === anchor.genre ? 0 : 7)));
      return {
        track: { ...track, musical_key: track.key },
        score,
        suggested_tempo: (track.bpm + anchor.bpm) / 2,
        suggested_pitch_semitones: 0,
        explanations: [
          `A working tempo around ${((track.bpm + anchor.bpm) / 2).toFixed(2)} BPM keeps both tracks close to their originals.`,
          track.key === anchor.key ? "The tracks share the same harmonic centre." : "Review the key shift before committing the overlay.",
          track.genre === anchor.genre ? "Shared genre language suggests compatible groove." : "The genre contrast may work best with isolated drums or vocals.",
        ],
        components: { tempo: Math.max(40, 100 - bpmDelta * 6), key: track.key === anchor.key ? 100 : 72, energy: 82, groove: track.genre === anchor.genre ? 100 : 58 },
      };
    })
    .sort((left, right) => right.score - left.score);
  return { anchor: { ...anchor, musical_key: anchor.key }, suggestions };
}

function statusLabel(status: AssistantDraft["status"]) {
  if (status === "needs_review") return "Needs review";
  if (status === "finished") return "In arrangement";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function ForgeWorkspace({ tracks, initialTrackId, onOpenArrangement }: {
  tracks: ForgeTrack[];
  initialTrackId?: number | null;
  onOpenArrangement: () => void;
}) {
  const [anchorId, setAnchorId] = useState(initialTrackId ?? tracks[0]?.id ?? 0);
  const [matches, setMatches] = useState<MatchPayload | null>(null);
  const [drafts, setDrafts] = useState<AssistantDraft[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setlist, setSetlist] = useState({ name: "", duration: 60, genre: "", curve: "rise", avoidTags: "" });
  const genres = useMemo(() => Array.from(new Set(tracks.map((track) => track.genre).filter(Boolean))).sort(), [tracks]);
  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) ?? drafts[0] ?? null;

  async function refreshMatches(nextAnchorId = anchorId) {
    if (!nextAnchorId) return;
    setBusy(true);
    setError(null);
    try {
      setMatches(isDesktop()
        ? await invoke<MatchPayload>("load_assistant_matches", { trackId: nextAnchorId, limit: 12 })
        : previewMatches(tracks, nextAnchorId));
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!tracks.length) return;
    const chosen = tracks.some((track) => track.id === anchorId) ? anchorId : tracks[0].id;
    setAnchorId(chosen);
    void refreshMatches(chosen);
    if (isDesktop()) {
      invoke<AssistantDraft[]>("load_assistant_drafts")
        .then((items) => { setDrafts(items); setSelectedDraftId(items[0]?.id ?? null); })
        .catch((reason) => setError(String(reason)));
    }
  // The library identity changes only when its track ids change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks.map((track) => track.id).join(",")]);

  async function createMashup(match: Match) {
    if (!matches) return;
    setBusy(true);
    setError(null);
    try {
      const draft = isDesktop()
        ? await invoke<AssistantDraft>("create_mashup_assistant_draft", {
          anchorTrackId: matches.anchor.id,
          partnerTrackId: match.track.id,
          name: "",
        })
        : {
          id: Date.now(), draft_kind: "mashup" as const,
          name: `${matches.anchor.title} × ${match.track.title}`,
          status: match.score >= 72 ? "ready" as const : "needs_review" as const,
          project_id: null,
          brief: { compatibility_score: match.score, working_tempo: match.suggested_tempo },
          updated_at: new Date().toISOString(),
          tracks: [
            { track_id: matches.anchor.id, title: matches.anchor.title, artist: matches.anchor.artist, position: 0, role: "foundation", compatibility_score: 100, suggested_tempo: match.suggested_tempo, suggested_pitch_semitones: 0, explanations: ["Foundation track for timing and structure."] },
            { track_id: match.track.id, title: match.track.title, artist: match.track.artist, position: 1, role: "overlay", compatibility_score: match.score, suggested_tempo: match.suggested_tempo, suggested_pitch_semitones: match.suggested_pitch_semitones, explanations: match.explanations },
          ],
        };
      setDrafts((items) => [draft, ...items]);
      setSelectedDraftId(draft.id);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createSetlist() {
    setBusy(true);
    setError(null);
    try {
      if (!isDesktop()) throw new Error("Saved setlist drafts are available in the desktop app.");
      const draft = await invoke<AssistantDraft>("create_setlist_assistant_draft", {
        name: setlist.name,
        durationMinutes: setlist.duration,
        genre: setlist.genre,
        energyCurve: setlist.curve,
        mustPlayTrackIds: [],
        avoidTags: setlist.avoidTags.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      setDrafts((items) => [draft, ...items]);
      setSelectedDraftId(draft.id);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function openDraftArrangement() {
    if (!selectedDraft || selectedDraft.draft_kind !== "mashup") return;
    setBusy(true);
    setError(null);
    try {
      if (isDesktop()) {
        await invoke("create_arrangement_from_assistant_draft", { draftId: selectedDraft.id });
      }
      onOpenArrangement();
    } catch (reason) {
      setError(String(reason));
      setBusy(false);
    }
  }

  if (!tracks.length) return <section className="forge-empty"><MusicNotes size={28} /><h1>The Forge needs a library</h1><p>Scan local music before asking Decksmith to build creative drafts.</p></section>;

  return <section className="forge-workspace" aria-label="The Forge workspace">
    <header className="forge-header">
      <div><span>The Forge</span><h1>Ideas, explained before they become edits.</h1><p>Every suggestion uses only your indexed local music. Decksmith scores and explains; you decide.</p></div>
      <div className="forge-local-badge"><CheckCircle size={16} weight="fill" /><strong>Local library only</strong><span>No uploads or cloud dependency</span></div>
    </header>
    {error && <div className="forge-error"><Warning size={15} /> {error}<button onClick={() => setError(null)}>Dismiss</button></div>}
    <div className="forge-grid">
      <main className="forge-main">
        <section className="forge-panel compatibility-panel">
          <div className="forge-panel-heading"><div><span>Compatibility engine</span><h2>Choose the foundation track</h2></div><Gauge size={20} /></div>
          <div className="forge-anchor-row"><select aria-label="Forge foundation track" value={anchorId} onChange={(event) => { const id = Number(event.target.value); setAnchorId(id); void refreshMatches(id); }}>{tracks.map((track) => <option value={track.id} key={track.id}>{track.artist} — {track.title}</option>)}</select><button disabled={busy} onClick={() => refreshMatches()}>{busy ? "Analysing…" : "Refresh matches"}</button></div>
          <div className="forge-match-list">{matches?.suggestions.map((match) => <article className="forge-match" key={match.track.id}>
            <div className="forge-score"><strong>{match.score}</strong><span>/100</span></div>
            <div className="forge-match-copy"><h3>{match.track.title}</h3><p>{match.track.artist} · {match.track.bpm?.toFixed(2) ?? "—"} BPM · {match.track.musical_key || "Key pending"}</p><div className="forge-component-bars">{Object.entries(match.components).map(([label, value]) => <span key={label}><small>{label}</small><i><b style={{ width: `${value}%` }} /></i></span>)}</div><ul>{match.explanations.slice(0, 2).map((reason) => <li key={reason}>{reason}</li>)}</ul></div>
            <button disabled={busy} onClick={() => createMashup(match)}><Sparkle size={13} weight="fill" /> Save draft</button>
          </article>)}</div>
        </section>
        <section className="forge-panel set-builder-panel">
          <div className="forge-panel-heading"><div><span>Set builder</span><h2>Build a local-only running order</h2></div><ListNumbers size={20} /></div>
          <div className="set-builder-form"><label><span>Name</span><input value={setlist.name} onChange={(event) => setSetlist({ ...setlist, name: event.target.value })} placeholder="Saturday sunset" /></label><label><span>Duration</span><input type="number" min="15" max="720" value={setlist.duration} onChange={(event) => setSetlist({ ...setlist, duration: Number(event.target.value) })} /><small>minutes</small></label><label><span>Genre</span><select value={setlist.genre} onChange={(event) => setSetlist({ ...setlist, genre: event.target.value })}><option value="">Entire library</option>{genres.map((genre) => <option key={genre}>{genre}</option>)}</select></label><label><span>Energy curve</span><select value={setlist.curve} onChange={(event) => setSetlist({ ...setlist, curve: event.target.value })}><option value="rise">Steady rise</option><option value="steady">Consistent</option><option value="wave">Wave</option></select></label><label className="set-avoid"><span>Avoid tags</span><input value={setlist.avoidTags} onChange={(event) => setSetlist({ ...setlist, avoidTags: event.target.value })} placeholder="explicit, warmup" /></label><button disabled={busy} onClick={createSetlist}>Build draft setlist <ArrowRight size={13} /></button></div>
        </section>
      </main>
      <aside className="forge-drafts">
        <div className="forge-panel-heading"><div><span>Saved work</span><h2>Drafts</h2></div><strong>{drafts.length}</strong></div>
        <div className="draft-list">{drafts.length === 0 && <p>No drafts yet. Save a pairing or build a setlist.</p>}{drafts.map((draft) => <button className={selectedDraft?.id === draft.id ? "active" : ""} key={draft.id} onClick={() => setSelectedDraftId(draft.id)}><span>{draft.draft_kind === "mashup" ? "Mashup" : "Setlist"}</span><strong>{draft.name}</strong><small>{statusLabel(draft.status)} · {draft.tracks.length} tracks</small></button>)}</div>
        {selectedDraft && <section className="draft-detail"><div className="draft-detail-head"><span>{selectedDraft.draft_kind}</span><h2>{selectedDraft.name}</h2><p>{statusLabel(selectedDraft.status)}{selectedDraft.brief.working_tempo ? ` · ${selectedDraft.brief.working_tempo.toFixed(2)} BPM` : selectedDraft.brief.duration_minutes ? ` · ${selectedDraft.brief.duration_minutes} min` : ""}</p></div><ol>{selectedDraft.tracks.map((track) => <li key={`${track.track_id}-${track.position}`}><span>{track.position + 1}</span><div><strong>{track.title}</strong><small>{track.artist} · {track.role}</small>{track.explanations[0] && <p>{track.explanations[0]}</p>}</div>{track.compatibility_score < 100 && <b>{Math.round(track.compatibility_score)}</b>}</li>)}</ol>{selectedDraft.draft_kind === "mashup" && <button className="draft-arrangement-button" disabled={busy} onClick={openDraftArrangement}>{selectedDraft.project_id ? "Open arrangement" : "Create arrangement"}<ArrowRight size={14} /></button>}</section>}
      </aside>
    </div>
  </section>;
}
