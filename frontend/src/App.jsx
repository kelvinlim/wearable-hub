import React, { useEffect, useState, useCallback } from "react";
import { api, apiBase } from "./api.js";

const today = () => new Date().toISOString().slice(0, 10);

export default function App() {
  const [me, setMe] = useState(undefined); // undefined = loading, null = logged out

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  if (me === undefined) return <div className="app muted">Loading…</div>;
  if (me === null) return <Login />;
  return <Console me={me} onLogout={() => setMe(null)} />;
}

function Login() {
  return (
    <div className="login">
      <div className="login-card">
        <h1>Wearable Hub</h1>
        <p className="muted">Researcher console</p>
        <a className="btn-link" href={`${apiBase}/auth/login`}>
          Sign in with Google
        </a>
      </div>
    </div>
  );
}

function Console({ me, onLogout }) {
  const [studies, setStudies] = useState([]);
  const [studyId, setStudyId] = useState(null);
  const [subjects, setSubjects] = useState([]);
  const [subject, setSubject] = useState(null);
  const [error, setError] = useState(null);

  const roleFor = useCallback(
    (id) =>
      me.is_superuser
        ? "super"
        : me.memberships.find((m) => m.study_id === id)?.role ?? null,
    [me]
  );
  const canAdmin = (id) => ["super", "admin"].includes(roleFor(id));

  const guard = useCallback(async (fn) => {
    try {
      setError(null);
      return await fn();
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const loadStudies = useCallback(
    () => guard(async () => setStudies(await api.listStudies())),
    [guard]
  );
  const loadSubjects = useCallback(
    (id) => guard(async () => setSubjects(await api.listSubjects(id))),
    [guard]
  );

  useEffect(() => {
    loadStudies();
  }, [loadStudies]);
  useEffect(() => {
    if (studyId != null) loadSubjects(studyId);
    setSubject(null);
  }, [studyId, loadSubjects]);

  return (
    <div className="app">
      <header>
        <h1>Wearable Hub</h1>
        <span className="muted">Researcher console</span>
        <span className="spacer" />
        <span className="muted">
          {me.email}
          {me.is_superuser ? <span className="badge ok"> superuser</span> : null}
        </span>
        <a className="enroll-link" href="/enroll" target="_blank" rel="noreferrer">
          Enrollment ↗
        </a>
        <button
          className="ghost"
          onClick={() =>
            guard(async () => {
              await api.logout();
              onLogout();
            })
          }
        >
          Sign out
        </button>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="cols">
        <div className="side">
          <StudiesPanel
            studies={studies}
            studyId={studyId}
            canCreate={me.is_superuser}
            onSelect={setStudyId}
            onCreate={(body) =>
              guard(async () => {
                await api.createStudy(body);
                loadStudies();
              })
            }
          />
          {me.is_superuser && <UsersPanel guard={guard} />}
        </div>

        <div className="main">
          {studyId == null ? (
            <p className="muted">Select or create a study.</p>
          ) : (
            <>
              <SubjectsPanel
                subjects={subjects}
                selected={subject}
                canAdmin={canAdmin(studyId)}
                onSelectSubject={setSubject}
                onAdd={(body) =>
                  guard(async () => {
                    await api.createSubject(studyId, body);
                    loadSubjects(studyId);
                  })
                }
              />
              {subject && (
                <SubjectDetail
                  subject={subject}
                  canAdmin={canAdmin(studyId)}
                  guard={guard}
                  onChanged={() => loadSubjects(studyId)}
                />
              )}
              {canAdmin(studyId) && <MembersPanel studyId={studyId} guard={guard} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StudiesPanel({ studies, studyId, canCreate, onSelect, onCreate }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <aside className="panel">
      <h2>Studies</h2>
      <ul className="list">
        {studies.map((s) => (
          <li key={s.id} className={s.id === studyId ? "active" : ""} onClick={() => onSelect(s.id)}>
            {s.name}
            {s.description ? <span className="muted"> — {s.description}</span> : null}
          </li>
        ))}
        {studies.length === 0 && <li className="muted">No studies.</li>}
      </ul>
      {canCreate && (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            onCreate({ name: name.trim(), description: description.trim() || null });
            setName("");
            setDescription("");
          }}
        >
          <input placeholder="New study name" value={name} onChange={(e) => setName(e.target.value)} />
          <input placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
          <button type="submit">Create study</button>
        </form>
      )}
    </aside>
  );
}

function SubjectsPanel({ subjects, selected, canAdmin, onSelectSubject, onAdd }) {
  const [label, setLabel] = useState("");
  return (
    <section className="panel">
      <h2>Subjects</h2>
      <table className="table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Entry code</th>
            <th>Status</th>
            <th>Linked</th>
          </tr>
        </thead>
        <tbody>
          {subjects.map((s) => (
            <tr key={s.id} className={selected?.id === s.id ? "active" : ""} onClick={() => onSelectSubject(s)}>
              <td>{s.subject_label || <span className="muted">—</span>}</td>
              <td><code>{s.entry_code}</code></td>
              <td>{s.status}</td>
              <td>{s.registered ? <span className="badge ok">linked</span> : <span className="badge">no</span>}</td>
            </tr>
          ))}
          {subjects.length === 0 && (
            <tr><td colSpan={4} className="muted">No subjects yet.</td></tr>
          )}
        </tbody>
      </table>
      {canAdmin && (
        <form
          className="form row"
          onSubmit={(e) => {
            e.preventDefault();
            onAdd({ subject_label: label.trim() || null });
            setLabel("");
          }}
        >
          <input placeholder="Subject label (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
          <button type="submit">Add subject (generates entry code)</button>
        </form>
      )}
    </section>
  );
}

function SubjectDetail({ subject, canAdmin, guard, onChanged }) {
  const [daily, setDaily] = useState([]);
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [busy, setBusy] = useState(false);
  const [openDay, setOpenDay] = useState(null);
  const [dayPts, setDayPts] = useState([]);

  const load = useCallback(() => guard(async () => setDaily(await api.daily(subject.id))), [guard, subject.id]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    setOpenDay(null);
    setDayPts([]);
  }, [subject.id]);

  const toggleDay = (date) =>
    guard(async () => {
      if (openDay === date) {
        setOpenDay(null);
        return;
      }
      setOpenDay(date);
      setDayPts(await api.dayPoints(subject.id, date));
    });

  return (
    <section className="panel">
      <h2>
        {subject.subject_label || "Subject"} <code>{subject.entry_code}</code>{" "}
        {subject.registered ? <span className="badge ok">linked</span> : <span className="badge">not linked</span>}
      </h2>

      {canAdmin && (
        <div className="actions">
          <label>From <input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label>To <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <button
            disabled={busy}
            onClick={() =>
              guard(async () => {
                setBusy(true);
                try {
                  await api.consolidate(subject.id, start, end);
                  await load();
                } finally {
                  setBusy(false);
                }
              })
            }
          >
            {busy ? "Pulling…" : "Pull + consolidate"}
          </button>
          <button
            className="danger"
            onClick={() => {
              if (!confirm("Revoke this subject's wearable authorization?")) return;
              guard(async () => {
                await api.revoke(subject.id);
                onChanged();
              });
            }}
          >
            Revoke access
          </button>
        </div>
      )}

      <table className="table">
        <thead>
          <tr>
            <th>Date</th><th>Steps</th><th>Distance (m)</th><th>Calories</th><th>Floors</th><th>Sleep (min)</th><th>Points</th>
          </tr>
        </thead>
        <tbody>
          {daily.map((d) => (
            <React.Fragment key={d.date}>
              <tr className="clickable" onClick={() => toggleDay(d.date)} title="Show intraday points">
                <td>{openDay === d.date ? "▾" : "▸"} {d.date}</td>
                <td>{fmt(d.steps)}</td>
                <td>{fmt(d.distance_m)}</td>
                <td>{fmt(d.calories)}</td>
                <td>{fmt(d.floors)}</td>
                <td>{fmt(d.sleep_minutes)}</td>
                <td className="muted">{d.point_count}</td>
              </tr>
              {openDay === d.date && (
                <tr className="detail-row">
                  <td colSpan={7}>
                    <PointsView points={dayPts} daily={d} />
                  </td>
                </tr>
              )}
            </React.Fragment>
          ))}
          {daily.length === 0 && (
            <tr><td colSpan={7} className="muted">No consolidated days yet.</td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function MembersPanel({ studyId, guard }) {
  const [members, setMembers] = useState([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");

  const load = useCallback(
    () => guard(async () => setMembers(await api.listMembers(studyId))),
    [guard, studyId]
  );
  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="panel">
      <h2>Study members</h2>
      <table className="table">
        <thead><tr><th>Email</th><th>Role</th><th></th></tr></thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id}>
              <td>{m.email}</td>
              <td>{m.role}</td>
              <td>
                <button className="ghost small" onClick={() => guard(async () => { await api.removeMember(studyId, m.user_id); load(); })}>
                  remove
                </button>
              </td>
            </tr>
          ))}
          {members.length === 0 && <tr><td colSpan={3} className="muted">No members.</td></tr>}
        </tbody>
      </table>
      <form
        className="form row"
        onSubmit={(e) => {
          e.preventDefault();
          if (!email.trim()) return;
          guard(async () => {
            await api.addMember(studyId, { email: email.trim(), role });
            setEmail("");
            load();
          });
        }}
      >
        <input placeholder="researcher@email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
        <button type="submit" disabled={!email.trim()}>Add / update member</button>
      </form>
      <p className="muted small">Researchers must first be added under "Researchers" by a superuser.</p>
    </section>
  );
}

function UsersPanel({ guard }) {
  const [users, setUsers] = useState([]);
  const [email, setEmail] = useState("");
  const [isSuper, setIsSuper] = useState(false);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => guard(async () => setUsers(await api.listUsers())), [guard]);
  useEffect(() => {
    if (open) load();
  }, [open, load]);

  return (
    <aside className="panel">
      <h2 className="clickable" onClick={() => setOpen((o) => !o)}>
        Researchers {open ? "▾" : "▸"}
      </h2>
      {open && (
        <>
          <ul className="list">
            {users.map((u) => (
              <li key={u.id}>
                {u.email} {u.is_superuser ? <span className="badge ok">super</span> : null}
                <button className="ghost small" onClick={() => guard(async () => { await api.deleteUser(u.id); load(); })}>×</button>
              </li>
            ))}
            {users.length === 0 && <li className="muted">No researchers.</li>}
          </ul>
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              if (!email.trim()) return;
              guard(async () => {
                await api.createUser({ email: email.trim(), is_superuser: isSuper });
                setEmail("");
                setIsSuper(false);
                load();
              });
            }}
          >
            <input placeholder="researcher@email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <label className="small"><input type="checkbox" checked={isSuper} onChange={(e) => setIsSuper(e.target.checked)} /> superuser</label>
            <button type="submit" disabled={!email.trim()}>Add researcher</button>
          </form>
        </>
      )}
    </aside>
  );
}

function fmt(v) {
  if (v == null) return <span className="muted">—</span>;
  return typeof v === "number" ? Math.round(v * 10) / 10 : v;
}

// UTC ISO + offset (seconds) -> local HH:MM
function localTime(iso, offsetSec) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (typeof offsetSec === "number") d.setTime(d.getTime() + offsetSec * 1000);
  return d.toISOString().slice(11, 16);
}

const STAGE_ORDER = ["DEEP", "REM", "LIGHT", "AWAKE"];

function stageMinutes(stages) {
  const m = {};
  for (const s of stages || []) {
    const a = new Date(s.start_time);
    const b = new Date(s.end_time);
    if (isNaN(a) || isNaN(b)) continue;
    m[s.type || "?"] = (m[s.type || "?"] || 0) + Math.round((b - a) / 60000);
  }
  return m;
}

function StageChips({ stages }) {
  const keys = STAGE_ORDER.filter((k) => stages?.[k]);
  if (!keys.length) return null;
  return (
    <span className="stagechips">
      {keys.map((k) => (
        <span key={k} className={`chip stage-${k.toLowerCase()}`}>
          {k.toLowerCase()} {stages[k]}m
        </span>
      ))}
    </span>
  );
}

function SleepGroup({ sessions, summary }) {
  return (
    <div className="ptgroup sleep">
      <div className="ptlabel">
        <strong>Sleep</strong>
        {summary ? (
          <span className="muted">
            {" "}· {summary.asleep_min}m asleep / {summary.total_min}m in bed · {summary.segments} session
            {summary.segments === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>
      {summary?.stages && (
        <div className="sleepday">
          <StageChips stages={summary.stages} />
        </div>
      )}
      <div className="sleepsessions">
        {sessions.map((s, i) => {
          const a = new Date(s.start_time + "Z");
          const b = new Date(s.end_time + "Z");
          const dur = !isNaN(a) && !isNaN(b) ? Math.round((b - a) / 60000) : null;
          return (
            <div key={i} className="sleepsession">
              <div className="small muted">
                {localTime(s.start_time, s.tz_offset_seconds)}–{localTime(s.end_time, s.tz_offset_seconds)}
                {dur != null ? ` · ${dur}m` : ""}
              </div>
              <StageChips stages={stageMinutes(s.stages)} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PointsView({ points, daily }) {
  if (!points.length)
    return (
      <div className="points muted">
        No intraday points for this day (floors &amp; calories are rollup-only — no raw points).
      </div>
    );
  const groups = {};
  for (const p of points) (groups[p.datatype] ||= []).push(p);
  return (
    <div className="points">
      {Object.entries(groups).map(([dt, list]) =>
        dt === "sleep" ? (
          <SleepGroup key="sleep" sessions={list} summary={daily?.metrics?.sleep} />
        ) : (
          <div key={dt} className="ptgroup">
            <div className="ptlabel">
              <strong>{dt}</strong> <span className="muted">· {list.length} pts</span>
            </div>
            <div className="ptscroll">
              <table className="table compact">
                <tbody>
                  {list.map((p, i) => (
                    <tr key={i}>
                      <td className="muted">
                        {localTime(p.start_time, p.tz_offset_seconds)}–
                        {localTime(p.end_time, p.tz_offset_seconds)}
                      </td>
                      <td>{fmt(p.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}
    </div>
  );
}
