"use client";
/**
 * Mockup state that outlives a page: routines, image history, captures, sessions, the live session, people,
 * zones, the waiting-on-a-person queue, and image notes.
 * Lives in the shell so client navigation keeps it; a reload resets it. Replace with the API when wiring.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import devicesFx from "@/lib/data/fixtures/devices.json";
import zonesFx from "@/lib/data/fixtures/zones.json";
import type { Device, Fixture, LedgerRow, Zone } from "@/lib/data";
import { INITIAL_PEOPLE, ME, type Member, type Role } from "@/lib/mock/people";
import { INITIAL_NOTES, INITIAL_WAITING, type Note, type WaitItem } from "@/lib/mock/waiting";
import { INITIAL_ROUTINES, TAKES_IMAGE, type Routine, type RoutineStep } from "@/lib/mock/routines";
import { INITIAL_CAPTURES, seedHistory, sceneSvg, type AreaImage, type Capture } from "@/lib/mock/images";
import { INITIAL_SESSIONS, type Session } from "@/lib/mock/sessions";

type XY = [number, number];
export interface Pose { position: XY; headingDeg: number }
/** `path` is what is left of a clicked-out drive: the points the dog still has to walk to. */
export interface Live { session: Session; pose: Pose; path: XY[] }

interface AppState {
  routines: Routine[];
  addRoutine: (r: Omit<Routine, "id">) => Routine;
  updateRoutine: (id: string, patch: Partial<Omit<Routine, "id">>) => void;
  images: AreaImage[];
  captures: Capture[];
  sessions: Session[];
  live: Live | null;
  startRoutine: (routineId: string) => void;
  startDriving: () => void;
  walkPath: (points: XY[]) => void;
  takePhoto: () => void;
  /** Ends the live session; `dest` sends the dog on to a saved place afterwards. */
  endSession: (dest?: { name: string; position: XY }) => void;

  me: string;
  people: Member[];
  addPerson: (p: Omit<Member, "id">) => void;
  setRole: (id: string, role: Role) => void;
  zones: Zone[];
  confirmZone: (zoneId: string) => void;
  waiting: WaitItem[];
  resolve: (id: string) => void;
  /** Person-assigned routine: puts it in that person's queue. */
  sendRoutine: (routineId: string) => void;
  notes: Note[];
  addNote: (n: Omit<Note, "id" | "at" | "authorId">) => void;
}

const Ctx = createContext<AppState | null>(null);
export function useApp() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppStateProvider");
  return v;
}

const body = (devicesFx as Fixture<Device[]>).data.find((d) => d.kind === "body")!;
const HOME: Pose = { position: body.position, headingDeg: body.headingDeg ?? 0 };
const STEP_MS = 1400;

const row = (tool: string, extra: Partial<LedgerRow> = {}): LedgerRow => ({
  ts: new Date().toISOString(), tool, ok: true, cached: true, source: "stub", latency_ms: 200 + Math.round(Math.random() * 900), ...extra,
});

/** The rows a routine run logs, one per tick: walk to each point, then do its action. */
function routineScript(r: Routine): Array<{ row: () => LedgerRow; at?: RoutineStep }> {
  const out: Array<{ row: () => LedgerRow; at?: RoutineStep }> = [];
  for (const st of r.steps) {
    out.push({ at: st, row: () => row("dog.follow", { args: { to: st.name, at: st.position } }) });
    out.push({ at: st, row: () => row(st.action === "lights_on" ? "lights.set" : st.action === "sit" ? "dog.sit" : "dog.look", { stop: st.id, args: { action: st.action, at: st.position } }) });
    if (TAKES_IMAGE.includes(st.action)) {
      out.push({ at: st, row: () => row("vision.check", { stop: st.id, args: { at: st.position }, state_after: { sentence: `${st.name}: nothing out of place.` } }) });
    }
  }
  out.push({ row: () => row("routine.done", { args: { routine: r.id } }) });
  return out;
}

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [routines, setRoutines] = useState<Routine[]>(INITIAL_ROUTINES);
  const [images, setImages] = useState<AreaImage[]>(() => seedHistory(INITIAL_ROUTINES.filter((r) => r.assignee.kind === "robot")));
  const [people, setPeople] = useState<Member[]>(INITIAL_PEOPLE);
  const [zones, setZones] = useState<Zone[]>((zonesFx as Fixture<Zone[]>).data);
  const [waiting, setWaiting] = useState<WaitItem[]>(INITIAL_WAITING);
  const [notes, setNotes] = useState<Note[]>(INITIAL_NOTES);
  const [captures, setCaptures] = useState<Capture[]>(INITIAL_CAPTURES);
  const [sessions, setSessions] = useState<Session[]>(INITIAL_SESSIONS);
  const [live, setLive] = useState<Live | null>(null);
  const script = useRef<ReturnType<typeof routineScript>>([]);
  const liveRef = useRef<Live | null>(null);
  useEffect(() => { liveRef.current = live; }, [live]);

  const nextId = () => Math.max(...sessions.map((s) => s.id), 0) + 1;

  const append = useCallback((r: LedgerRow, pose?: Partial<Pose>) => {
    setLive((l) => (l ? { ...l, session: { ...l.session, rows: [...l.session.rows, r] }, pose: { ...l.pose, ...pose } } : l));
  }, []);

  const endSession = useCallback((dest?: { name: string; position: XY }) => {
    const l = liveRef.current;
    if (!l) return;
    const last = l.session.rows[l.session.rows.length - 1]?.tool;
    const rows = last === "routine.done" ? [...l.session.rows] : [...l.session.rows, row(l.session.kind === "routine" ? "routine.stop" : "drive.stop")];
    if (dest) rows.push(row("dog.goto", { args: { to: dest.name, at: dest.position } }));
    else if (last !== "routine.done") rows.push(row("dog.sit", { args: { action: "stay" } }));
    setSessions((ss) => [{ ...l.session, endedAt: new Date().toISOString(), rows }, ...ss]);
    setLive(null);
    liveRef.current = null;
    script.current = [];
  }, []);

  const startRoutine = useCallback((routineId: string) => {
    const r = routines.find((x) => x.id === routineId);
    if (!r || live) return;
    script.current = routineScript(r);
    setLive({ session: { id: nextId(), kind: "routine", routineId, startedAt: new Date().toISOString(), rows: [row("routine.start", { args: { routine: r.id } })] }, pose: HOME, path: [] });
    setRoutines((rs) => rs.map((x) => (x.id === routineId ? { ...x, lastRun: new Date().toISOString() } : x)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routines, live, sessions]);

  const startDriving = useCallback(() => {
    if (live) return;
    setLive({ session: { id: nextId(), kind: "driving", startedAt: new Date().toISOString(), rows: [row("drive.start")] }, pose: HOME, path: [] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, sessions]);

  /* Play the routine script, one row per tick. */
  const routineRunning = live?.session.kind === "routine";
  useEffect(() => {
    if (!routineRunning) return;
    const t = setInterval(() => {
      const next = script.current.shift();
      if (!next) return;
      const r = next.row();
      append(r, next.at ? { position: next.at.position } : undefined);
      const routineId = liveRef.current?.session.routineId;
      if (next.at && routineId && r.tool === "dog.look" && TAKES_IMAGE.includes(next.at.action)) {
        const st = next.at;
        setImages((im) => [...im, { id: `${routineId}:${st.id}:${r.ts}`, routineId, stepId: st.id, takenAt: r.ts, image: sceneSvg(st.name, r.ts.slice(0, 10), 1, 1) }]);
      }
      if (r.tool === "routine.done") {
        toast("Routine finished");
        setTimeout(endSession, STEP_MS);
      }
    }, STEP_MS);
    return () => clearInterval(t);
  }, [routineRunning, append, endSession]);

  /* Driving: walk a clicked-out path one point per tick, facing each point as it goes. */
  const walkPath = useCallback((points: XY[]) => {
    if (points.length === 0) return;
    setLive((l) => (l && l.session.kind === "driving"
      ? { ...l, path: [...l.path, ...points], session: { ...l.session, rows: [...l.session.rows, row("dog.path", { args: { points: points.length } })] } }
      : l));
  }, []);

  const walking = live?.session.kind === "driving" && live.path.length > 0;
  useEffect(() => {
    if (!walking) return;
    const t = setInterval(() => {
      setLive((l) => {
        if (!l || l.path.length === 0) return l;
        const [next, ...rest] = l.path;
        const [x, y] = l.pose.position;
        const headingDeg = Math.round((Math.atan2(next[1] - y, next[0] - x) * 180) / Math.PI);
        const rows = [...l.session.rows, row("dog.move", { args: { at: next } })];
        if (rest.length === 0) rows.push(row("dog.arrived", { args: { at: next } }));
        return { session: { ...l.session, rows }, pose: { position: next, headingDeg }, path: rest };
      });
    }, 900);
    return () => clearInterval(t);
  }, [walking]);

  const takePhoto = useCallback(() => {
    if (!live || live.session.kind !== "driving") return;
    const r = row("dog.look", { args: { kind: "photo", at: live.pose.position } });
    append(r);
    const near = `${live.pose.position[0].toFixed(1)}, ${live.pose.position[1].toFixed(1)} m`;
    setCaptures((c) => [{ id: r.ts, takenAt: r.ts, sessionId: live.session.id, near, image: sceneSvg(near, r.ts.slice(0, 10), 0.5, captures.length) }, ...c]);
    toast("Photo taken");
  }, [live, append, captures.length]);

  const addRoutine = useCallback((r: Omit<Routine, "id">) => {
    const created = { ...r, id: `${r.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now().toString(36)}` };
    setRoutines((rs) => [...rs, created]);
    return created;
  }, []);

  const updateRoutine = useCallback((id: string, patch: Partial<Omit<Routine, "id">>) => {
    setRoutines((rs) => rs.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  }, []);

  const addPerson = useCallback((p: Omit<Member, "id">) => {
    setPeople((ps) => [...ps, { ...p, id: `${p.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now().toString(36)}` }]);
  }, []);
  const setRole = useCallback((id: string, role: Role) => setPeople((ps) => ps.map((p) => (p.id === id ? { ...p, role } : p))), []);

  const resolve = useCallback((id: string) => setWaiting((w) => w.filter((x) => x.id !== id)), []);

  const confirmZone = useCallback((zoneId: string) => {
    setZones((zs) => zs.map((z) => (z.id === zoneId ? { ...z, kind: "nogo", status: "rule", name: z.name.replace(/^Proposed:\s*/i, "") } : z)));
    setWaiting((w) => w.filter((x) => x.zoneId !== zoneId));
  }, []);

  const sendRoutine = useCallback((routineId: string) => {
    const r = routines.find((x) => x.id === routineId);
    if (!r || r.assignee.kind !== "person") return;
    const personId = r.assignee.personId;
    setWaiting((w) => (w.some((x) => x.routineId === routineId) ? w : [{
      id: `w-routine-${routineId}-${Date.now().toString(36)}`, kind: "routine", personId, since: new Date().toISOString(),
      title: `Walk ${r.name}`, detail: `${r.steps.length} points, in order.`, routineId, href: `/routines/${routineId}`,
    }, ...w]));
  }, [routines]);

  const addNote = useCallback((n: Omit<Note, "id" | "at" | "authorId">) => {
    const note: Note = { ...n, id: `n-${Date.now().toString(36)}`, at: new Date().toISOString(), authorId: ME };
    setNotes((ns) => [...ns, note]);
    const author = people.find((p) => p.id === ME)?.name ?? "Someone";
    const step = routines.find((r) => r.id === n.routineId)?.steps.find((st) => st.id === n.stepId);
    const mentioned = people.filter((p) => p.id !== ME && n.text.includes(`@${p.name}`));
    if (mentioned.length) {
      setWaiting((w) => [...mentioned.map((p) => ({
        id: `w-note-${note.id}-${p.id}`, kind: "mention" as const, personId: p.id, since: note.at,
        title: `${author} mentioned you on ${step?.name ?? "an image"}`, detail: n.text.replace(/@([A-Z][\w-]*(?: [A-Z][\w-]*)?)/g, "$1"),
        href: `/images/${n.routineId}/${n.stepId}`,
      })), ...w]);
    }
  }, [people, routines]);

  const value = useMemo<AppState>(() => ({
    routines, addRoutine, updateRoutine, images, captures, sessions, live, startRoutine, startDriving, walkPath, takePhoto, endSession,
    me: ME, people, addPerson, setRole, zones, confirmZone, waiting, resolve, sendRoutine, notes, addNote,
  }), [routines, addRoutine, updateRoutine, images, captures, sessions, live, startRoutine, startDriving, walkPath, takePhoto, endSession,
    people, addPerson, setRole, zones, confirmZone, waiting, resolve, sendRoutine, notes, addNote]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
