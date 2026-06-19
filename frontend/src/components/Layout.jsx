import React, { useState } from "react";
import {
  Activity,
  BookOpen,
  Users,
  ShieldCheck,
  Info,
  Moon,
  Sun,
  LogOut,
  ChevronRight,
  User as UserIcon,
} from "lucide-react";
import { cn } from "../lib";
import { Select } from "../ui";

const TITLES = {
  studies: "Studies",
  subjects: "Subjects",
  researchers: "Research staff",
  about: "About",
};

export default function Layout({
  currentView,
  onNavigate,
  me,
  onLogout,
  studies = [],
  selectedStudyId,
  onStudyChange,
  dark,
  onToggleDark,
  children,
}) {
  const [open, setOpen] = useState(true);

  const nav = [
    { id: "studies", name: "Studies", icon: BookOpen },
    { id: "subjects", name: "Subjects", icon: Users },
    ...(me?.is_superuser ? [{ id: "researchers", name: "Research staff", icon: ShieldCheck }] : []),
    { id: "about", name: "About", icon: Info },
  ];
  const showStudyPicker = currentView === "studies" || currentView === "subjects";
  const role = me?.is_superuser ? "Superuser" : "Researcher";

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className={cn(
          "flex flex-col bg-maroon text-white shadow-xl transition-all duration-300",
          open ? "w-64" : "w-20"
        )}
      >
        <div className="flex items-center gap-3 border-b border-white/10 p-5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-gold text-maroon">
            <Activity className="h-6 w-6" strokeWidth={2.5} />
          </div>
          {open && (
            <div className="flex flex-col leading-tight">
              <span className="font-display text-lg font-bold tracking-tight">Wearable Hub</span>
              <span className="flex items-baseline gap-1.5 text-[10px] uppercase tracking-widest text-white/60">
                Research console
                <span className="tracking-normal normal-case text-white/40">v{__APP_VERSION__}</span>
              </span>
            </div>
          )}
        </div>

        <nav className="flex-1 space-y-1.5 px-3 py-5">
          {nav.map((item) => (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={cn(
                "group relative flex w-full items-center gap-4 rounded-lg p-3 transition-colors",
                !open && "justify-center",
                currentView === item.id
                  ? "bg-white/15 font-semibold text-white"
                  : "text-white/70 hover:bg-white/10 hover:text-white"
              )}
            >
              <item.icon className="h-5 w-5 shrink-0" />
              {open && <span className="text-sm">{item.name}</span>}
              {!open && (
                <span className="pointer-events-none absolute left-full z-50 ml-3 whitespace-nowrap rounded bg-neutral-900 px-2 py-1 text-xs opacity-0 transition-opacity group-hover:opacity-100">
                  {item.name}
                </span>
              )}
            </button>
          ))}
        </nav>

        <div className="border-t border-white/10 p-3">
          <button
            onClick={() => setOpen((o) => !o)}
            className="mb-3 flex w-full items-center justify-center rounded-lg border border-white/20 p-2 transition-colors hover:bg-white/10"
          >
            <ChevronRight className={cn("h-5 w-5 transition-transform", open && "rotate-180")} />
          </button>
          <div className={cn("flex items-center gap-3 p-1", !open && "justify-center")}>
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gold text-maroon">
              <UserIcon className="h-5 w-5" />
            </div>
            {open && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{me?.email}</p>
                <p className="truncate text-[10px] italic text-white/60">{role}</p>
              </div>
            )}
            {open && (
              <button onClick={onLogout} title="Sign out" className="text-white/50 transition-colors hover:text-gold">
                <LogOut className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="z-10 flex min-h-16 flex-wrap items-center gap-4 border-b border-gray-200 bg-white px-8 py-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="font-display text-xl font-bold text-maroon dark:text-gold">{TITLES[currentView]}</h2>
          {showStudyPicker && (
            <div className="ml-2 flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-1 dark:border-neutral-700 dark:bg-neutral-800">
              <span className="text-[10px] font-bold uppercase tracking-tight text-gray-400">Study</span>
              <select
                value={selectedStudyId ?? ""}
                onChange={(e) => onStudyChange(e.target.value ? Number(e.target.value) : null)}
                className="bg-transparent text-sm font-medium text-gray-800 outline-none dark:text-neutral-100"
              >
                <option value="">— select —</option>
                {studies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <button
            onClick={onToggleDark}
            title="Toggle dark mode"
            className="ml-auto flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 text-gray-500 transition hover:bg-gray-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
          >
            {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </button>
        </header>

        <main className="flex-1 overflow-y-auto bg-gray-50 p-6 dark:bg-neutral-950">{children}</main>
      </div>
    </div>
  );
}
