import React, { useEffect, useMemo, useState, useCallback } from "react";
import {
  Plus, Trash2, Lock, Pencil, X, ChevronUp, ChevronDown,
  BatteryFull, BatteryWarning, AlertTriangle, Download,
} from "lucide-react";
import { api } from "../api";
import { providerLabel, download, dailyCsv, pointsCsv } from "../lib";
import { usePhiPrivacy } from "../phiPrivacy";
import {
  maskParticipantId, maskSubjectLabel, subjectDisplayName,
  subjectDeletePromptId, typedDeleteConfirmationMatches, subjectExportBasename,
} from "../utils/phi";
import { Card, Button, Badge, Input, Th, Td, Empty, Field } from "../ui";
import SubjectDetail from "./SubjectDetail";

// Compact "start → end" window label for the table; "—" when no window is set.
function windowLabel(s) {
  if (!s.collection_start && !s.collection_end) return null;
  return `${s.collection_start || "…"} → ${s.collection_end || "…"}`;
}

const dash = <span className="text-gray-300 dark:text-neutral-600">—</span>;

// Per-subject device registration: the subject's one device (the study's provider) — a chip with
// the entry code + linked dot. Normally auto-created with the subject; the re-issue button only
// appears if the registration was deleted.
function DevicesCell({ s, studyProvider, canAdmin, guard, onChanged }) {
  const regs = s.registrations || [];
  return (
    <div className="flex flex-col items-start gap-1" onClick={(e) => e.stopPropagation()}>
      {regs.map((r) => (
        <Badge key={r.id} tone={r.registered ? "green" : "gray"} className="gap-1">
          <span className="font-semibold">{providerLabel(r.provider)}</span>
          <code className="rounded bg-black/5 px-1 text-[11px] dark:bg-white/10">{r.entry_code}</code>
          {r.registered ? "✓" : ""}
        </Badge>
      ))}
      {regs.length === 0 && canAdmin && (
        <button
          title={`Issue ${providerLabel(studyProvider)} entry code`}
          onClick={() => guard(async () => { await api.addRegistration(s.id, studyProvider); onChanged(); })}
          className="inline-flex items-center gap-0.5 rounded border border-dashed border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-500 hover:border-maroon hover:text-maroon dark:border-neutral-700 dark:hover:border-gold dark:hover:text-gold"
        >
          <Plus className="h-3 w-3" />{providerLabel(studyProvider)} code
        </button>
      )}
      {regs.length === 0 && !canAdmin && <span className="text-xs text-gray-300">no device</span>}
    </div>
  );
}

// --- Sorting ---------------------------------------------------------------
const SORTERS = {
  label: (s) => (s.subject_label || "").toLowerCase(),
  status: (s) => s.status || "",
  linked: (s) => (s.registered ? 1 : 0),
};
const DEFAULT_DIR = { label: "asc", status: "asc", linked: "desc" };

function SortTh({ label, sortKey, sort, onSort, className }) {
  const active = sort.key === sortKey;
  return (
    <Th className={className}>
      <button
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider hover:text-maroon dark:hover:text-gold"
      >
        {label}
        {active && (sort.dir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
      </button>
    </Th>
  );
}

// --- Compact health indicators ---------------------------------------------
const BATT_TONE = { High: "green", Medium: "gold", Low: "red", Empty: "red" };

function relDay(d) {
  if (!d) return null;
  const then = new Date(d + "T00:00:00");
  const days = Math.round((new Date(new Date().toDateString()) - new Date(then.toDateString())) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return d;
}

function BatteryCell({ s }) {
  if (!s.registered || s.battery_level == null) return dash;
  const Icon = s.battery_low ? BatteryWarning : BatteryFull;
  return (
    <Badge tone={s.battery_low ? "red" : BATT_TONE[s.battery_status] || "gray"} className="gap-1">
      <Icon className="h-3.5 w-3.5" />
      {s.battery_level}%
    </Badge>
  );
}

// 7-pip bar of last-week coverage + the "n/7" count; flags a stale badge alongside.
function WeekDataCell({ s }) {
  if (!s.registered) return dash;
  const n = s.days_with_data_7 || 0;
  const tone = n >= 6 ? "bg-green-500" : n >= 3 ? "bg-gold" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5">
        {Array.from({ length: 7 }).map((_, i) => (
          <span key={i} className={"h-3 w-1.5 rounded-sm " + (i < n ? tone : "bg-gray-200 dark:bg-neutral-700")} />
        ))}
      </div>
      <span className="text-xs text-gray-500">{n}/7</span>
      {s.data_stale && (
        <Badge tone="red" className="gap-1"><AlertTriangle className="h-3 w-3" />stale</Badge>
      )}
    </div>
  );
}

function LatestCell({ s }) {
  if (!s.registered) return dash;
  const rel = relDay(s.last_data_date);
  if (!rel) return <span className="text-xs text-red-600">none</span>;
  return <span className={"whitespace-nowrap text-xs " + (s.data_stale ? "text-red-600" : "text-gray-500")}>{rel}</span>;
}

export default function SubjectsView({ studyId, studyProvider = "fitbit_gh", canAdmin, guard }) {
  const { hidePhi } = usePhiPrivacy();
  const [subjects, setSubjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [pid, setPid] = useState("");
  const [editing, setEditing] = useState(null); // subject being edited, or null
  const [deleting, setDeleting] = useState(null); // subject in the delete-confirm modal, or null
  const [sort, setSort] = useState({ key: "linked", dir: "desc" }); // linked-first by default

  const onSort = (k) =>
    setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: DEFAULT_DIR[k] }));

  const sorted = useMemo(() => {
    const f = SORTERS[sort.key];
    return [...subjects].sort((a, b) => {
      const av = f(a), bv = f(b);
      let c = av < bv ? -1 : av > bv ? 1 : 0;
      if (c === 0) c = a.id - b.id;
      return sort.dir === "asc" ? c : -c;
    });
  }, [subjects, sort]);

  const load = useCallback(() => {
    if (studyId != null)
      guard(async () => {
        const list = await api.listSubjects(studyId);
        setSubjects(list);
        // Keep the open detail panel in sync after add-device / revoke / edit.
        setSelected((sel) => (sel ? list.find((x) => x.id === sel.id) || null : null));
      });
  }, [studyId, guard]);
  useEffect(() => {
    setSelected(null);
    setSubjects([]);
    load();
  }, [load]);

  if (studyId == null)
    return (
      <Card className="p-10 text-center text-sm text-gray-400">
        Select a study from the header dropdown to view its subjects.
      </Card>
    );

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-gray-100 p-4 dark:border-neutral-800">
          <h3 className="font-display text-base font-semibold text-maroon dark:text-gold">Subjects</h3>
          {canAdmin && (
            <Button onClick={() => setAdding((a) => !a)}>
              <Plus className="h-4 w-4" /> Add subject
            </Button>
          )}
        </div>

        {adding && canAdmin && (
          <form
            className="flex flex-wrap items-center gap-2 border-b border-gray-100 bg-gray-50 p-4 dark:border-neutral-800 dark:bg-neutral-800/40"
            onSubmit={(e) => {
              e.preventDefault();
              guard(async () => {
                await api.createSubject(studyId, {
                  subject_label: label.trim() || null,
                  participant_id: pid.trim() || null,
                });
                setLabel("");
                setPid("");
                setAdding(false);
                load();
              });
            }}
          >
            <Input placeholder="Study ID (optional)" value={pid} onChange={(e) => setPid(e.target.value)} autoFocus />
            <Input placeholder="Label — account (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
            <span className="self-center text-xs text-gray-400">Device: <b>{providerLabel(studyProvider)}</b> (from study)</span>
            <Button type="submit">Create — generates entry code</Button>
            <Button type="button" variant="subtle" onClick={() => setAdding(false)}>Cancel</Button>
          </form>
        )}

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-100 dark:border-neutral-800">
              <tr>
                <Th>Devices</Th>
                <Th>Study ID</Th>
                <SortTh label="Label" sortKey="label" sort={sort} onSort={onSort} />
                <Th>Battery</Th>
                <Th>Data (7d)</Th>
                <Th>Latest</Th>
                <Th>Collection window</Th>
                <SortTh label="Status" sortKey="status" sort={sort} onSort={onSort} />
                <SortTh label="Linked" sortKey="linked" sort={sort} onSort={onSort} />
                {canAdmin && <Th />}
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => {
                const win = windowLabel(s);
                return (
                  <tr
                    key={s.id}
                    onClick={() => setSelected(s)}
                    className={
                      "cursor-pointer border-b border-gray-50 transition-colors hover:bg-gray-50 dark:border-neutral-800/60 dark:hover:bg-neutral-800/50 " +
                      (selected?.id === s.id ? "bg-maroon/5 dark:bg-maroon/20" : "")
                    }
                  >
                    <Td><DevicesCell s={s} studyProvider={studyProvider} canAdmin={canAdmin} guard={guard} onChanged={load} /></Td>
                    <Td className="font-medium">{maskParticipantId(s.participant_id, hidePhi) || dash}</Td>
                    <Td>{maskSubjectLabel(s, hidePhi) || dash}</Td>
                    <Td><BatteryCell s={s} /></Td>
                    <Td><WeekDataCell s={s} /></Td>
                    <Td><LatestCell s={s} /></Td>
                    <Td className="whitespace-nowrap text-xs text-gray-500">{win || <span className="text-gray-300">—</span>}</Td>
                    <Td className="text-gray-500">{s.status}</Td>
                    <Td>{s.registered ? <Badge tone="green">linked</Badge> : <Badge>no</Badge>}</Td>
                    {canAdmin && (
                      <Td className="text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-3">
                          <button
                            title="Edit subject (Study ID, label, collection window)"
                            onClick={() => setEditing(s)}
                            className="text-gray-400 hover:text-maroon dark:hover:text-gold"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          {!s.registered ? (
                            <button
                              title="Delete subject (permanent — extra confirmation required)"
                              onClick={() => setDeleting(s)}
                              className="text-gray-400 hover:text-red-600"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          ) : (
                            <span
                              title="Linked — revoke this subject's access before it can be deleted"
                              className="inline-flex cursor-help text-gray-300 dark:text-neutral-600"
                            >
                              <Lock className="h-4 w-4" />
                            </span>
                          )}
                        </div>
                      </Td>
                    )}
                  </tr>
                );
              })}
              {subjects.length === 0 && (
                <tr><td colSpan={canAdmin ? 10 : 9}><Empty>No subjects yet.</Empty></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {selected && <SubjectDetail subject={selected} canAdmin={canAdmin} guard={guard} onChanged={load} />}

      {editing && (
        <EditSubjectModal
          subject={editing}
          guard={guard}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setEditing(null);
            if (selected?.id === updated.id) setSelected(updated);
            load();
          }}
        />
      )}

      {deleting && (
        <DeleteSubjectModal
          subject={deleting}
          hidePhi={hidePhi}
          guard={guard}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            if (selected?.id === deleting.id) setSelected(null);
            setDeleting(null);
            load();
          }}
        />
      )}
    </div>
  );
}

const DELETE_HOLD_S = 2;

function DeleteSubjectModal({ subject, hidePhi, guard, onClose, onDeleted }) {
  const [step, setStep] = useState(1);
  const [preview, setPreview] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const [typed, setTyped] = useState("");
  const [exportedAck, setExportedAck] = useState(false);
  const [exportedNote, setExportedNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [holdLeft, setHoldLeft] = useState(0);
  const promptId = subjectDeletePromptId(subject, hidePhi);
  const idMatches = typedDeleteConfirmationMatches(subject, typed);

  useEffect(() => {
    let alive = true;
    api.subjectDeletionPreview(subject.id)
      .then((p) => { if (alive) setPreview(p); })
      .catch((e) => { if (alive) setLoadErr(e.message || "Failed to load preview"); });
    return () => { alive = false; };
  }, [subject.id]);

  useEffect(() => {
    if (step !== 3 || !exportedAck) {
      setHoldLeft(0);
      return undefined;
    }
    setHoldLeft(DELETE_HOLD_S);
    const started = Date.now();
    const id = setInterval(() => {
      const left = Math.max(0, DELETE_HOLD_S - Math.floor((Date.now() - started) / 1000));
      setHoldLeft(left);
      if (left === 0) clearInterval(id);
    }, 200);
    return () => clearInterval(id);
  }, [step, exportedAck]);

  const doExport = (fmt) =>
    guard(async () => {
      const data = await api.exportSubject(subject.id);
      const base = subjectExportBasename(subject, hidePhi);
      if (fmt === "json") download(`${base}.json`, "application/json", JSON.stringify(data, null, 2));
      else if (fmt === "csv-daily") download(`${base}-daily.csv`, "text/csv", dailyCsv(data));
      else download(`${base}-points.csv`, "text/csv", pointsCsv(data));
      setExportedNote("Export downloaded. You still need to confirm on the last step.");
    });

  const doDelete = () =>
    guard(async () => {
      setBusy(true);
      try {
        await api.deleteSubject(subject.id, {
          confirm: true,
          confirm_participant_id: typed.trim(),
          confirm_exported: true,
        });
        onDeleted();
      } finally {
        setBusy(false);
      }
    });

  const range = preview && (preview.first_date || preview.last_date)
    ? `${preview.first_date || "…"} → ${preview.last_date || "…"}`
    : "no data yet";
  const canDelete = step === 3 && exportedAck && holdLeft === 0 && !busy && preview && !preview.linked;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <Card className="w-full max-w-lg">
        <div onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between border-b border-gray-100 p-4 dark:border-neutral-800">
            <h3 className="font-display text-base font-semibold text-red-700 dark:text-red-400">
              Permanently delete participant
            </h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="h-4 w-4" /></button>
          </div>

          <div className="space-y-4 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
              Step {step} of 3
            </p>

            {step === 1 && (
              <>
                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
                  <p className="font-semibold">This cannot be undone.</p>
                  <p className="mt-1">
                    Revoking a wearable only disconnects the device and <b>keeps</b> the health data.
                    Deleting the participant destroys every daily row, every intraday point, device
                    registrations, and the subject record.
                  </p>
                </div>

                {loadErr && <p className="text-sm text-red-600">{loadErr}</p>}
                {!preview && !loadErr && <p className="text-sm text-gray-400">Loading data counts…</p>}
                {preview && (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                    <dt className="text-gray-400">Study</dt>
                    <dd className="font-medium">{preview.study_name || "—"}</dd>
                    <dt className="text-gray-400">Study ID</dt>
                    <dd className="font-medium">
                      {hidePhi
                        ? <span className="text-gray-400">hidden — type <code className="rounded bg-gray-100 px-1 dark:bg-neutral-800">{promptId}</code> on the next step</span>
                        : (preview.participant_id || <span className="text-gray-400">none — use {preview.fallback_id}</span>)}
                    </dd>
                    <dt className="text-gray-400">Internal id</dt>
                    <dd><code className="rounded bg-gray-100 px-1 text-xs dark:bg-neutral-800">{preview.fallback_id}</code></dd>
                    <dt className="text-gray-400">Daily rows</dt>
                    <dd>{preview.daily_row_count}</dd>
                    <dt className="text-gray-400">Intraday points</dt>
                    <dd>{preview.point_count}</dd>
                    <dt className="text-gray-400">Date range</dt>
                    <dd>{range}</dd>
                  </dl>
                )}

                <div>
                  <p className="mb-2 text-sm text-gray-600 dark:text-neutral-300">
                    Export this participant first. The download uses the same JSON/CSV as the detail view.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="ghost" onClick={() => doExport("json")}><Download className="h-4 w-4" /> JSON</Button>
                    <Button variant="ghost" onClick={() => doExport("csv-daily")}><Download className="h-4 w-4" /> CSV — daily</Button>
                    <Button variant="ghost" onClick={() => doExport("csv-points")}><Download className="h-4 w-4" /> CSV — points</Button>
                  </div>
                  {exportedNote && <p className="mt-2 text-xs text-gray-500">{exportedNote}</p>}
                </div>
              </>
            )}

            {step === 2 && (
              <>
                <p className="text-sm text-gray-600 dark:text-neutral-300">
                  Type <code className="rounded bg-gray-100 px-1.5 py-0.5 font-semibold dark:bg-neutral-800">{promptId}</code> to continue.
                  {hidePhi && " Hide PHI is on, so the Study ID is not shown — the internal id is enough."}
                </p>
                <Field label="Confirmation">
                  <Input
                    className="w-full font-mono"
                    autoFocus
                    autoComplete="off"
                    spellCheck={false}
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                    placeholder={promptId}
                  />
                </Field>
                {typed && !idMatches && (
                  <p className="text-xs text-red-600">That does not match.</p>
                )}
              </>
            )}

            {step === 3 && (
              <>
                <p className="text-sm text-gray-600 dark:text-neutral-300">
                  Last step. After you check the box there is a short pause before Delete is enabled.
                </p>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={exportedAck}
                    onChange={(e) => setExportedAck(e.target.checked)}
                  />
                  <span>
                    I have exported or backed up this participant&apos;s data. I understand it will be
                    permanently destroyed.
                  </span>
                </label>
                {preview?.linked && (
                  <p className="text-sm text-red-600">
                    This subject is still linked. Revoke their wearable access first.
                  </p>
                )}
              </>
            )}
          </div>

          <div className="flex justify-end gap-2 border-t border-gray-100 p-4 dark:border-neutral-800">
            {step === 1 && (
              <>
                <Button variant="subtle" onClick={onClose}>Cancel</Button>
                <Button onClick={() => setStep(2)} disabled={!preview || preview.linked}>Continue</Button>
              </>
            )}
            {step === 2 && (
              <>
                <Button variant="subtle" onClick={() => setStep(1)}>Back</Button>
                <Button onClick={() => setStep(3)} disabled={!idMatches}>Continue</Button>
              </>
            )}
            {step === 3 && (
              <>
                <Button variant="subtle" onClick={() => setStep(2)}>Back</Button>
                <Button variant="danger" onClick={doDelete} disabled={!canDelete}>
                  {busy ? "Deleting…" : holdLeft > 0 ? `Wait ${holdLeft}s…` : "Delete participant"}
                </Button>
              </>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

function EditSubjectModal({ subject, guard, onClose, onSaved }) {
  const { hidePhi } = usePhiPrivacy();
  const [pid, setPid] = useState(subject.participant_id || "");
  const [label, setLabel] = useState(subject.subject_label || "");
  const [start, setStart] = useState(subject.collection_start || "");
  const [end, setEnd] = useState(subject.collection_end || "");
  const [busy, setBusy] = useState(false);

  const rangeBad = start && end && end < start;

  const save = () =>
    guard(async () => {
      setBusy(true);
      try {
        const updated = await api.updateSubject(subject.id, {
          participant_id: pid.trim() || null,
          subject_label: label.trim() || null,
          collection_start: start || null,
          collection_end: end || null,
        });
        onSaved(updated);
      } finally {
        setBusy(false);
      }
    });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <Card className="w-full max-w-md" >
        <div onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between border-b border-gray-100 p-4 dark:border-neutral-800">
            <h3 className="font-display text-base font-semibold text-maroon dark:text-gold">
              Edit subject
              <code className="ml-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">{subjectDisplayName(subject, hidePhi)}</code>
            </h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="h-4 w-4" /></button>
          </div>

          <div className="space-y-4 p-4">
            <Field label="Study ID">
              <Input className="w-full" placeholder="Study's subject identifier" value={pid} onChange={(e) => setPid(e.target.value)} />
            </Field>
            <Field label="Label (Google account)">
              <Input className="w-full" placeholder="Google / Fitbit account" value={label} onChange={(e) => setLabel(e.target.value)} />
            </Field>

            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Data-collection window</div>
              <div className="flex items-center gap-2">
                <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
                <span className="text-gray-400">→</span>
                <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
              </div>
              <p className="mt-1.5 text-xs text-gray-400">
                Inclusive, subject-local days. Leave a side blank for open-ended. Pulls are clamped to this window across all triggers.
              </p>
              {rangeBad && <p className="mt-1 text-xs text-red-600">End date must be on or after the start date.</p>}
            </div>
          </div>

          <div className="flex justify-end gap-2 border-t border-gray-100 p-4 dark:border-neutral-800">
            <Button variant="subtle" onClick={onClose}>Cancel</Button>
            <Button onClick={save} disabled={busy || rangeBad}>{busy ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
