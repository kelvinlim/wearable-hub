import React, { useEffect, useState, useCallback } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Input, Th, Td, Empty, SectionTitle } from "../ui";

export default function ResearchersView({ guard }) {
  const [users, setUsers] = useState([]);
  const [email, setEmail] = useState("");
  const [isSuper, setIsSuper] = useState(false);

  const load = useCallback(() => guard(async () => setUsers(await api.listUsers())), [guard]);
  useEffect(() => { load(); }, [load]);

  return (
    <Card className="max-w-2xl overflow-hidden">
      <div className="border-b border-gray-100 p-4 dark:border-neutral-800"><SectionTitle>Research staff</SectionTitle></div>
      <table className="w-full">
        <thead className="border-b border-gray-100 dark:border-neutral-800"><tr><Th>Email</Th><Th>Role</Th><Th></Th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-gray-50 dark:border-neutral-800/60">
              <Td className="font-medium">{u.email}</Td>
              <Td>{u.is_superuser ? <Badge tone="maroon">superuser</Badge> : <Badge>researcher</Badge>}</Td>
              <Td className="text-right">
                <button onClick={() => guard(async () => { await api.deleteUser(u.id); load(); })} className="text-gray-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
              </Td>
            </tr>
          ))}
          {users.length === 0 && <tr><td colSpan={3}><Empty>No researchers.</Empty></td></tr>}
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
    </Card>
  );
}
