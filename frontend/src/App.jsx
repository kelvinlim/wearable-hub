import React, { useEffect, useState, useCallback } from "react";
import { X } from "lucide-react";
import { api } from "./api";
import Layout from "./components/Layout";
import LoginView from "./views/LoginView";
import StudiesView from "./views/StudiesView";
import SubjectsView from "./views/SubjectsView";
import ResearchersView from "./views/ResearchersView";
import AboutView from "./views/AboutView";

export default function App() {
  const [me, setMe] = useState(undefined); // undefined=loading, null=logged out
  const [view, setView] = useState("studies");
  const [studies, setStudies] = useState([]);
  const [selectedStudyId, setSelectedStudyId] = useState(null);
  const [error, setError] = useState(null);
  const [dark, setDark] = useState(() => localStorage.getItem("wh-dark") === "1");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("wh-dark", dark ? "1" : "0");
  }, [dark]);

  const guard = useCallback(async (fn) => {
    try {
      setError(null);
      return await fn();
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const reloadStudies = useCallback(
    () =>
      guard(async () => {
        const s = await api.listStudies();
        setStudies(s);
        setSelectedStudyId((prev) => (prev ?? (s[0]?.id ?? null)));
      }),
    [guard]
  );

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (me) reloadStudies();
  }, [me, reloadStudies]);

  if (me === undefined)
    return <div className="flex h-screen items-center justify-center text-gray-400">Loading…</div>;
  if (me === null) return <LoginView />;

  const roleFor = (id) =>
    me.is_superuser ? "super" : me.memberships?.find((m) => m.study_id === id)?.role ?? null;
  const canAdmin = ["super", "admin"].includes(roleFor(selectedStudyId));

  return (
    <Layout
      currentView={view}
      onNavigate={setView}
      me={me}
      onLogout={() => guard(async () => { await api.logout(); setMe(null); })}
      studies={studies}
      selectedStudyId={selectedStudyId}
      onStudyChange={setSelectedStudyId}
      dark={dark}
      onToggleDark={() => setDark((d) => !d)}
    >
      {view === "studies" && (
        <StudiesView
          studies={studies}
          selectedStudyId={selectedStudyId}
          onStudyChange={setSelectedStudyId}
          reloadStudies={reloadStudies}
          canAdmin={canAdmin}
          isSuper={me.is_superuser}
          guard={guard}
        />
      )}
      {view === "subjects" && <SubjectsView studyId={selectedStudyId} canAdmin={canAdmin} guard={guard} />}
      {view === "researchers" && me.is_superuser && <ResearchersView guard={guard} />}
      {view === "about" && <AboutView me={me} />}

      {error && (
        <div className="fixed bottom-4 right-4 z-50 flex max-w-md items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-lg dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600"><X className="h-4 w-4" /></button>
        </div>
      )}
    </Layout>
  );
}
