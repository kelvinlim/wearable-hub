// Thin wrapper over the backend admin API. Paths are relative (same-origin): nginx proxies
// /admin and /enroll to the backend in the container; Vite proxies them in dev.

async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  listStudies: () => req("/admin/studies"),
  createStudy: (body) =>
    req("/admin/studies", { method: "POST", body: JSON.stringify(body) }),
  listSubjects: (studyId) => req(`/admin/studies/${studyId}/subjects`),
  createSubject: (studyId, body) =>
    req(`/admin/studies/${studyId}/subjects`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  daily: (subjectId) => req(`/admin/subjects/${subjectId}/daily`),
  consolidate: (subjectId, start, end) =>
    req(`/admin/subjects/${subjectId}/consolidate?start=${start}&end=${end}`, {
      method: "POST",
    }),
  revoke: (subjectId) =>
    req(`/admin/subjects/${subjectId}/revoke`, { method: "POST" }),
};
