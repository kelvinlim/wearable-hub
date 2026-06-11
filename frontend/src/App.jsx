import React, { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";

const today = () => new Date().toISOString().slice(0, 10);

export default function App() {
  const [studies, setStudies] = useState([]);
  const [studyId, setStudyId] = useState(null);
  const [subjects, setSubjects] = useState([]);
  const [subject, setSubject] = useState(null); // selected subject object
  const [error, setError] = useState(null);

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
        <a className="enroll-link" href="/enroll" target="_blank" rel="noreferrer">
          Open enrollment page ↗
        </a>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="cols">
        <StudiesPanel
          studies={studies}
          studyId={studyId}
          onSelect={setStudyId}
          onCreate={(body) =>
            guard(async () => {
              await api.createStudy(body);
              loadStudies();
            })
          }
        />

        <div className="main">
          {studyId == null ? (
            <p className="muted">Select or create a study to manage its subjects.</p>
          ) : (
            <SubjectsPanel
              subjects={subjects}
              selected={subject}
              onSelectSubject={setSubject}
              onAdd={(body) =>
                guard(async () => {
                  await api.createSubject(studyId, body);
                  loadSubjects(studyId);
                })
              }
            />
          )}

          {subject && (
            <SubjectDetail
              subject={subject}
              guard={guard}
              onChanged={() => loadSubjects(studyId)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function StudiesPanel({ studies, studyId, onSelect, onCreate }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <aside className="panel">
      <h2>Studies</h2>
      <ul className="list">
        {studies.map((s) => (
          <li
            key={s.id}
            className={s.id === studyId ? "active" : ""}
            onClick={() => onSelect(s.id)}
          >
            {s.name}
            {s.description ? <span className="muted"> — {s.description}</span> : null}
          </li>
        ))}
        {studies.length === 0 && <li className="muted">No studies yet.</li>}
      </ul>
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
        <input
          placeholder="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <button type="submit">Create study</button>
      </form>
    </aside>
  );
}

function SubjectsPanel({ subjects, selected, onSelectSubject, onAdd }) {
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
            <tr
              key={s.id}
              className={selected?.id === s.id ? "active" : ""}
              onClick={() => onSelectSubject(s)}
            >
              <td>{s.subject_label || <span className="muted">—</span>}</td>
              <td>
                <code>{s.entry_code}</code>
              </td>
              <td>{s.status}</td>
              <td>{s.registered ? <span className="badge ok">linked</span> : <span className="badge">no</span>}</td>
            </tr>
          ))}
          {subjects.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                No subjects yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
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
    </section>
  );
}

function SubjectDetail({ subject, guard, onChanged }) {
  const [daily, setDaily] = useState([]);
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () => guard(async () => setDaily(await api.daily(subject.id))),
    [guard, subject.id]
  );
  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="panel">
      <h2>
        {subject.subject_label || "Subject"} <code>{subject.entry_code}</code>{" "}
        {subject.registered ? <span className="badge ok">linked</span> : <span className="badge">not linked</span>}
      </h2>

      <div className="actions">
        <label>
          From <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          To <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
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

      <table className="table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Steps</th>
            <th>Distance (m)</th>
            <th>Calories</th>
            <th>Floors</th>
            <th>Sleep (min)</th>
            <th>Points</th>
          </tr>
        </thead>
        <tbody>
          {daily.map((d) => (
            <tr key={d.date}>
              <td>{d.date}</td>
              <td>{fmt(d.steps)}</td>
              <td>{fmt(d.distance_m)}</td>
              <td>{fmt(d.calories)}</td>
              <td>{fmt(d.floors)}</td>
              <td>{fmt(d.sleep_minutes)}</td>
              <td className="muted">{d.point_count}</td>
            </tr>
          ))}
          {daily.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                No consolidated days yet — pull a date range above.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function fmt(v) {
  if (v == null) return <span className="muted">—</span>;
  return typeof v === "number" ? Math.round(v * 10) / 10 : v;
}
