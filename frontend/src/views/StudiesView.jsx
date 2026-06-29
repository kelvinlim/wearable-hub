import React, { useEffect, useState, useCallback } from "react";
import { Plus, Download, Trash2, HeartPulse } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Input, Select, Th, Td, Empty, SectionTitle } from "../ui";
import { download, studyDailyCsv, studyPointsCsv, ALL_PROVIDERS, providerLabel } from "../lib";

export default function StudiesView({ studies, selectedStudyId, onStudyChange, reloadStudies, canAdmin, isSuper, guard }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [provider, setProvider] = useState("fitbit_gh");
  const selected = studies.find((s) => s.id === selectedStudyId) || null;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1.2fr]">
      <Card className="overflow-hidden self-start">
        <div className="border-b border-gray-100 p-4 dark:border-neutral-800">
          <SectionTitle>Studies</SectionTitle>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-100 dark:border-neutral-800">
              <tr><Th>Name</Th><Th>Device</Th><Th>Intraday</Th></tr>
            </thead>
            <tbody>
              {studies.map((s) => (
                <tr
                  key={s.id}
                  onClick={() => onStudyChange(s.id)}
                  className={
                    "cursor-pointer border-b border-gray-50 hover:bg-gray-50 dark:border-neutral-800/60 dark:hover:bg-neutral-800/50 " +
                    (selectedStudyId === s.id ? "bg-maroon/5 dark:bg-maroon/20" : "")
                  }
                >
                  <Td>
                    <div className="font-medium">{s.name}</div>
                    {s.description && <div className="text-xs text-gray-400">{s.description}</div>}
                  </Td>
                  <Td><Badge tone="maroon">{providerLabel(s.provider)}</Badge></Td>
                  <Td><IntradayFlags study={s} /></Td>
                </tr>
              ))}
              {studies.length === 0 && <tr><td colSpan={3}><Empty>No studies.</Empty></td></tr>}
            </tbody>
          </table>
        </div>
        {isSuper && (
          <form
            className="flex flex-col gap-2 border-t border-gray-100 p-4 dark:border-neutral-800"
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              guard(async () => {
                await api.createStudy({ name: name.trim(), description: desc.trim() || null, provider });
                setName(""); setDesc(""); setProvider("fitbit_gh"); reloadStudies();
              });
            }}
          >
            <Input placeholder="New study name" value={name} onChange={(e) => setName(e.target.value)} />
            <Input placeholder="Description (optional)" value={desc} onChange={(e) => setDesc(e.target.value)} />
            <label className="flex items-center gap-2 text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Device</span>
              <Select value={provider} onChange={(e) => setProvider(e.target.value)}>
                {ALL_PROVIDERS.map((p) => <option key={p} value={p}>{providerLabel(p)}</option>)}
              </Select>
              <span className="text-xs text-gray-400">(can't be changed later)</span>
            </label>
            <Button type="submit" className="self-start"><Plus className="h-4 w-4" /> Create study</Button>
          </form>
        )}
      </Card>

      {selected ? (
        <div className="space-y-5">
          <SettingsCard study={selected} canAdmin={canAdmin} guard={guard} onChanged={reloadStudies} />
          {canAdmin && <MembersCard studyId={selected.id} guard={guard} />}
        </div>
      ) : (
        <Card className="p-10 text-center text-sm text-gray-400">Select a study to manage its settings, members, and export.</Card>
      )}
    </div>
  );
}

// Compact on/off badges for the three intraday opt-ins.
function IntradayFlags({ study }) {
  const on = [
    study.ingest_intraday_hr && "HR",
    study.ingest_intraday_hrv && "HRV",
    study.ingest_intraday_spo2 && "SpO₂",
    study.ingest_intraday_activity && "Activity",
    study.ingest_intraday_stress && "Stress",
  ].filter(Boolean);
  if (!on.length) return <span className="text-gray-300">off</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {on.map((l) => <Badge key={l} tone="maroon">{l}</Badge>)}
    </div>
  );
}

const INTRADAY_OPTS = [
  { key: "ingest_intraday_hr", label: "heart rate (downsampled)" },
  { key: "ingest_intraday_hrv", label: "HRV (raw sleep samples)" },
  { key: "ingest_intraday_spo2", label: "SpO₂ (downsampled, avg + min)" },
  { key: "ingest_intraday_activity", label: "steps over time (Fitbit; Garmin epochs)" },
  { key: "ingest_intraday_stress", label: "stress + body battery (downsampled, Garmin)" },
];

function SettingsCard({ study, canAdmin, guard, onChanged }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [fmt, setFmt] = useState("json");
  const [busy, setBusy] = useState(false);

  const runExport = () =>
    guard(async () => {
      setBusy(true);
      try {
        const data = await api.exportStudy(study.id, from || undefined, to || undefined);
        const base = `study-${(study.name || "study").replace(/\s+/g, "_")}`;
        if (fmt === "json") download(`${base}.json`, "application/json", JSON.stringify(data, null, 2));
        else if (fmt === "csv-daily") download(`${base}-daily.csv`, "text/csv", studyDailyCsv(data));
        else download(`${base}-points.csv`, "text/csv", studyPointsCsv(data));
      } finally { setBusy(false); }
    });

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <SectionTitle>{study.name}</SectionTitle>
        <Badge tone="maroon">{providerLabel(study.provider)}</Badge>
        <span className="text-xs text-gray-400">device fixed at creation</span>
      </div>

      {canAdmin && (
        <div className="mb-4 space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            <HeartPulse className="h-4 w-4 text-maroon dark:text-gold" /> Intraday ingestion
          </div>
          {INTRADAY_OPTS.map((opt) => (
            <label key={opt.key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-maroon"
                checked={!!study[opt.key]}
                onChange={(e) => guard(async () => { await api.updateStudy(study.id, { [opt.key]: e.target.checked }); onChanged(); })}
              />
              {opt.label}
            </label>
          ))}
          <p className="text-xs text-gray-400">
            Raw HRV/SpO₂ are sleep-period samples; subjects need the matching scopes granted.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Study export</span>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
        <span className="text-gray-400">→</span>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
        <Select value={fmt} onChange={(e) => setFmt(e.target.value)} className="py-1">
          <option value="json">JSON</option>
          <option value="csv-daily">CSV — daily</option>
          <option value="csv-points">CSV — points</option>
        </Select>
        <Button variant="ghost" disabled={busy} onClick={runExport}><Download className="h-4 w-4" /> {busy ? "Building…" : "Download all subjects"}</Button>
      </div>
    </Card>
  );
}

const NEW_STAFF = "__new__";

function MembersCard({ studyId, guard }) {
  const [members, setMembers] = useState([]);
  const [assignable, setAssignable] = useState([]);
  const [pick, setPick] = useState("");       // selected researcher email, or NEW_STAFF, or ""
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [role, setRole] = useState("member");

  const load = useCallback(() => guard(async () => {
    const [m, a] = await Promise.all([api.listMembers(studyId), api.assignableUsers(studyId)]);
    setMembers(m);
    setAssignable(a);
  }), [guard, studyId]);
  useEffect(() => { load(); }, [load]);

  const addingNew = pick === NEW_STAFF;
  const email = addingNew ? newEmail.trim() : pick;

  const submit = (e) => {
    e.preventDefault();
    if (!email) return;
    guard(async () => {
      await api.addMember(studyId, { email, name: addingNew ? (newName.trim() || null) : null, role });
      setPick(""); setNewEmail(""); setNewName(""); setRole("member");
      load();
    });
  };

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-gray-100 p-4 dark:border-neutral-800"><SectionTitle>Research staff</SectionTitle></div>
      <table className="w-full">
        <thead className="border-b border-gray-100 dark:border-neutral-800"><tr><Th>Email</Th><Th>Role</Th><Th></Th></tr></thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id} className="border-b border-gray-50 dark:border-neutral-800/60">
              <Td>{m.email}</Td>
              <Td><Badge tone={m.role === "admin" ? "maroon" : "gray"}>{m.role}</Badge></Td>
              <Td className="text-right">
                <button onClick={() => guard(async () => { await api.removeMember(studyId, m.user_id); load(); })} className="text-gray-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
              </Td>
            </tr>
          ))}
          {members.length === 0 && <tr><td colSpan={3}><Empty>No members.</Empty></td></tr>}
        </tbody>
      </table>
      <form className="flex flex-wrap items-center gap-2 border-t border-gray-100 p-4 dark:border-neutral-800" onSubmit={submit}>
        <Select value={pick} onChange={(e) => setPick(e.target.value)} className="min-w-[14rem]">
          <option value="">Select a researcher…</option>
          {assignable.map((u) => (
            <option key={u.id} value={u.email}>{u.name ? `${u.name} — ${u.email}` : u.email}</option>
          ))}
          <option value={NEW_STAFF}>➕ Add new researcher…</option>
        </Select>
        {addingNew && (
          <>
            <Input placeholder="researcher@email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} autoFocus />
            <Input placeholder="Name (optional)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          </>
        )}
        <Select value={role} onChange={(e) => setRole(e.target.value)}><option value="member">member</option><option value="admin">admin</option></Select>
        <Button type="submit" disabled={!email}>Add / update</Button>
      </form>
      <p className="px-4 pb-4 text-xs text-gray-400">Pick an existing researcher, or “Add new researcher…” to onboard someone by email (created as a non-superuser).</p>
    </Card>
  );
}
