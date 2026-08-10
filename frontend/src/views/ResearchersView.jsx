import React, { useEffect, useState, useCallback } from "react";
import { Plus, Trash2, Pencil, X } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Input, Th, Td, Empty, SectionTitle, Field } from "../ui";

// Staff-editable first/last, falling back to the Google display name.
function displayName(u) {
  return [u.first_name, u.last_name].filter(Boolean).join(" ") || u.name || "";
}

export default function ResearchersView({ guard }) {
  const [users, setUsers] = useState([]);
  const [email, setEmail] = useState("");
  const [isSuper, setIsSuper] = useState(false);
  const [editing, setEditing] = useState(null); // researcher being edited, or null

  const load = useCallback(() => guard(async () => setUsers(await api.listUsers())), [guard]);
  useEffect(() => { load(); }, [load]);

  return (
    <Card className="max-w-3xl overflow-hidden">
      <div className="border-b border-gray-100 p-4 dark:border-neutral-800"><SectionTitle>Research staff</SectionTitle></div>
      <table className="w-full">
        <thead className="border-b border-gray-100 dark:border-neutral-800"><tr><Th>Name</Th><Th>Email</Th><Th>Role</Th><Th></Th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-gray-50 dark:border-neutral-800/60">
              <Td className="font-medium">{displayName(u) || <span className="text-gray-300 dark:text-neutral-600">—</span>}</Td>
              <Td>{u.email}</Td>
              <Td>{u.is_superuser ? <Badge tone="maroon">superuser</Badge> : <Badge>researcher</Badge>}</Td>
              <Td className="text-right">
                <div className="flex items-center justify-end gap-3">
                  <button title="Edit researcher" onClick={() => setEditing(u)} className="text-gray-400 hover:text-maroon dark:hover:text-gold"><Pencil className="h-4 w-4" /></button>
                  <button title="Remove researcher" onClick={() => guard(async () => { await api.deleteUser(u.id); load(); })} className="text-gray-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                </div>
              </Td>
            </tr>
          ))}
          {users.length === 0 && <tr><td colSpan={4}><Empty>No researchers.</Empty></td></tr>}
        </tbody>
      </table>
      <form
        className="flex flex-wrap items-center gap-3 border-t border-gray-100 p-4 dark:border-neutral-800"
        onSubmit={(e) => { e.preventDefault(); if (!email.trim()) return; guard(async () => { await api.createUser({ email: email.trim(), is_superuser: isSuper }); setEmail(""); setIsSuper(false); load(); }); }}
      >
        <Input placeholder="researcher@email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <label className="flex items-center gap-1.5 text-sm text-gray-600 dark:text-neutral-300">
          <input type="checkbox" className="h-4 w-4 accent-maroon" checked={isSuper} onChange={(e) => setIsSuper(e.target.checked)} /> superuser
        </label>
        <Button type="submit" disabled={!email.trim()}><Plus className="h-4 w-4" /> Add researcher</Button>
      </form>

      {editing && (
        <EditResearcherModal
          user={editing}
          guard={guard}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </Card>
  );
}

function EditResearcherModal({ user, guard, onClose, onSaved }) {
  const [first, setFirst] = useState(user.first_name || "");
  const [last, setLast] = useState(user.last_name || "");
  const [email, setEmail] = useState(user.email || "");
  const [isSuper, setIsSuper] = useState(!!user.is_superuser);
  const [busy, setBusy] = useState(false);

  const emailChanged = email.trim().toLowerCase() !== (user.email || "").toLowerCase();

  const save = () =>
    guard(async () => {
      setBusy(true);
      try {
        const updated = await api.updateUser(user.id, {
          first_name: first.trim() || null,
          last_name: last.trim() || null,
          email: email.trim(),
          is_superuser: isSuper,
        });
        onSaved(updated);
      } finally {
        setBusy(false);
      }
    });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <Card className="w-full max-w-md">
        <div onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between border-b border-gray-100 p-4 dark:border-neutral-800">
            <h3 className="font-display text-base font-semibold text-maroon dark:text-gold">Edit researcher</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="h-4 w-4" /></button>
          </div>

          <div className="space-y-4 p-4">
            <div className="flex gap-3">
              <div className="flex-1"><Field label="First name"><Input className="w-full" value={first} onChange={(e) => setFirst(e.target.value)} /></Field></div>
              <div className="flex-1"><Field label="Last name"><Input className="w-full" value={last} onChange={(e) => setLast(e.target.value)} /></Field></div>
            </div>
            <Field label="Email">
              <Input className="w-full" type="email" placeholder="researcher@umn.edu" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            {emailChanged && (
              <p className="-mt-2 text-xs text-gray-400">
                This is the Google account they sign in with. Changing it unlinks the old account.
              </p>
            )}
            <label className="flex items-center gap-1.5 text-sm text-gray-600 dark:text-neutral-300">
              <input type="checkbox" className="h-4 w-4 accent-maroon" checked={isSuper} onChange={(e) => setIsSuper(e.target.checked)} /> superuser
            </label>
          </div>

          <div className="flex justify-end gap-2 border-t border-gray-100 p-4 dark:border-neutral-800">
            <Button variant="subtle" onClick={onClose}>Cancel</Button>
            <Button onClick={save} disabled={busy || !email.trim()}>{busy ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
