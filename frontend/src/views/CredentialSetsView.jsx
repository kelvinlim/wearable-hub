import React, { useEffect, useState } from "react";
import { Plus, Trash2, KeyRound, ExternalLink } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Input, Th, Td, Empty, SectionTitle } from "../ui";

// Superuser-only management of Google credential sets (each = one GCP project). Secrets are
// write-only: the server never returns them, only whether each is configured.

// Only client id/secret + scopes are used by the current enrollment/retrieval flow. The
// subscriber/webhook fields (project, subscriber, SA JSON, webhook secret) aren't used yet — they're
// for the Phase-2 real-time push per project — so they live under an "Advanced" section, and blank
// ones fall back to the global env creds server-side.

// Defaults prefilled into the "New" form — mirror the global .env (GOOGLE_HEALTH_SCOPES,
// GH_SUBSCRIPTION_DATA_TYPES, GH_SUBSCRIPTION_CREATE_POLICY). Editing an existing set never uses these.
const DEFAULT_SCOPES = [
  "openid",
  "email",
  "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
  "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
  "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
  "https://www.googleapis.com/auth/googlehealth.profile.readonly",
  "https://www.googleapis.com/auth/googlehealth.settings.readonly",
].join(" ");
const DEFAULT_DATA_TYPES = "steps sleep distance calories floors weight height exercise altitude";

const BLANK = {
  name: "", oauth_client_id: "", oauth_client_secret: "",
  health_scopes: DEFAULT_SCOPES,
  gh_project_id: "", gh_project_number: "", gh_subscriber_id: "",
  gh_subscription_create_policy: "AUTOMATIC",
  gh_subscription_data_types: DEFAULT_DATA_TYPES,
  sa_json: "", webhook_secret: "", console_url: "",
};

// Module-scope so inputs don't remount (and lose focus) on each keystroke.
function Field({ label, hint, value, onChange, ...props }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-400">
        {label}
        {hint && <em className="ml-1 normal-case text-gray-400">{hint}</em>}
      </span>
      <Input value={value} onChange={onChange} {...props} />
    </label>
  );
}

export default function CredentialSetsView({ guard }) {
  const [sets, setSets] = useState([]);
  const [editing, setEditing] = useState(null); // null | {id?, ...form, _has}

  const reload = () => guard(async () => setSets(await api.listCredentialSets()));
  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const startEdit = (c) =>
    setEditing({
      id: c.id, name: c.name || "", oauth_client_id: c.oauth_client_id || "",
      oauth_client_secret: "", health_scopes: c.health_scopes || "",
      gh_project_id: c.gh_project_id || "", gh_project_number: c.gh_project_number || "",
      gh_subscriber_id: c.gh_subscriber_id || "",
      gh_subscription_create_policy: c.gh_subscription_create_policy || "",
      gh_subscription_data_types: c.gh_subscription_data_types || "",
      sa_json: "", webhook_secret: "", console_url: c.console_url || "",
      _has: { secret: c.has_client_secret, sa: c.has_sa_json, webhook: c.has_webhook_secret },
    });

  const save = () =>
    guard(async () => {
      const { id, _has, ...body } = editing;
      if (id) await api.updateCredentialSet(id, body);
      else await api.createCredentialSet(body);
      setEditing(null);
      reload();
    });

  const del = (c) =>
    guard(async () => {
      if (!window.confirm(`Delete credential set “${c.name}”?`)) return;
      await api.deleteCredentialSet(c.id);
      if (editing?.id === c.id) setEditing(null);
      reload();
    });

  const set = (k, v) => setEditing((e) => ({ ...e, [k]: v }));
  const has = editing?._has || {};
  // Auto-expand Advanced when editing a set that already has subscriber/webhook fields set.
  const advConfigured = !!(
    has.sa || has.webhook || editing?.gh_project_id || editing?.gh_project_number || editing?.gh_subscriber_id
  );
  const needsSecret = editing && !editing.id && editing.oauth_client_id && !editing.oauth_client_secret;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1.1fr]">
      <Card className="overflow-hidden self-start">
        <div className="flex items-center justify-between border-b border-gray-100 p-4 dark:border-neutral-800">
          <SectionTitle>Google projects</SectionTitle>
          <Button onClick={() => setEditing({ ...BLANK })}><Plus className="h-4 w-4" /> New</Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-100 dark:border-neutral-800">
              <tr><Th>Name</Th><Th>Project ID</Th><Th>Configured</Th><Th>Studies</Th><Th></Th></tr>
            </thead>
            <tbody>
              {sets.map((c) => (
                <tr key={c.id} onClick={() => startEdit(c)} className="cursor-pointer border-b border-gray-50 hover:bg-gray-50 dark:border-neutral-800/60 dark:hover:bg-neutral-800/50">
                  <Td><div className="font-medium">{c.name}</div></Td>
                  <Td>
                    {c.console_url ? (
                      <a href={c.console_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 text-maroon hover:underline dark:text-gold">
                        {c.gh_project_id || "—"} <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : (c.gh_project_id || "—")}
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {c.has_client_secret && <Badge tone="maroon">secret</Badge>}
                      {c.has_sa_json && <Badge tone="maroon">SA</Badge>}
                      {c.has_webhook_secret && <Badge tone="maroon">webhook</Badge>}
                      {!c.has_client_secret && !c.has_sa_json && !c.has_webhook_secret && <span className="text-gray-300">—</span>}
                    </div>
                  </Td>
                  <Td className="text-gray-400">{c.study_count}</Td>
                  <Td>
                    <button
                      title={c.study_count ? "Reassign its studies first" : "Delete"}
                      disabled={c.study_count > 0}
                      onClick={(e) => { e.stopPropagation(); del(c); }}
                      className="text-gray-400 hover:text-red-600 disabled:opacity-30"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </Td>
                </tr>
              ))}
              {sets.length === 0 && <tr><td colSpan={5}><Empty>No credential sets — all studies use the global env creds.</Empty></td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      {editing ? (
        <Card className="space-y-3 p-4">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-maroon dark:text-gold" />
            <SectionTitle>{editing.id ? "Edit project" : "New project"}</SectionTitle>
          </div>
          <Field label="Name" value={editing.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Sleep Study — Project A" />
          <Field label="OAuth client ID *" value={editing.oauth_client_id} onChange={(e) => set("oauth_client_id", e.target.value)} placeholder="…apps.googleusercontent.com" />
          <Field label="OAuth client secret *" hint={has.secret ? "— configured" : null} type="password" value={editing.oauth_client_secret} onChange={(e) => set("oauth_client_secret", e.target.value)} placeholder={has.secret ? "(unchanged)" : ""} autoComplete="new-password" />
          {needsSecret && (
            <p className="-mt-1 text-xs text-amber-600 dark:text-amber-400">
              Set the client secret too — required for a Web OAuth client. A client ID without its secret would fall back to the global secret.
            </p>
          )}
          <Field label="Health scopes" hint="— space-separated; blank = global" value={editing.health_scopes} onChange={(e) => set("health_scopes", e.target.value)} />
          <Field label="GCP Console URL" hint="— informational" value={editing.console_url} onChange={(e) => set("console_url", e.target.value)} placeholder="https://console.cloud.google.com/…" />

          <details key={editing.id ?? "new"} open={advConfigured} className="rounded-lg border border-gray-200 p-3 dark:border-neutral-700">
            <summary className="cursor-pointer select-none text-xs font-semibold uppercase tracking-wide text-gray-400">
              Advanced — subscriber &amp; webhook <span className="normal-case text-gray-400">(not used yet; for real-time push)</span>
            </summary>
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Full project ID" value={editing.gh_project_id} onChange={(e) => set("gh_project_id", e.target.value)} placeholder="fitbitdata-499001" />
                <Field label="Project number" value={editing.gh_project_number} onChange={(e) => set("gh_project_number", e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Subscriber ID" value={editing.gh_subscriber_id} onChange={(e) => set("gh_subscriber_id", e.target.value)} />
                <Field label="Subscription policy" value={editing.gh_subscription_create_policy} onChange={(e) => set("gh_subscription_create_policy", e.target.value)} placeholder="AUTOMATIC" />
              </div>
              <Field label="Subscription data types" hint="— space-separated" value={editing.gh_subscription_data_types} onChange={(e) => set("gh_subscription_data_types", e.target.value)} />
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-400">
                  Service-account JSON {has.sa && <em className="normal-case text-gray-400">— configured</em>}
                </span>
                <textarea rows={4} value={editing.sa_json} onChange={(e) => set("sa_json", e.target.value)} placeholder={has.sa ? "(unchanged) — paste new JSON to replace" : "{ … }"} className="w-full rounded-lg border border-gray-300 px-2 py-1 font-mono text-xs dark:border-neutral-700 dark:bg-neutral-800" />
              </label>
              <Field label="Webhook secret" hint={has.webhook ? "— configured" : null} type="password" value={editing.webhook_secret} onChange={(e) => set("webhook_secret", e.target.value)} placeholder={has.webhook ? "(unchanged)" : ""} autoComplete="new-password" />
            </div>
          </details>

          <div className="flex gap-2">
            <Button onClick={save}>{editing.id ? "Save" : "Create"}</Button>
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
          </div>
          <p className="text-xs text-gray-400">Secrets are write-only — never displayed. Leave a secret blank to keep the stored value.</p>
        </Card>
      ) : (
        <Card className="p-10 text-center text-sm text-gray-400">Select a project to edit, or create a new one.</Card>
      )}
    </div>
  );
}
