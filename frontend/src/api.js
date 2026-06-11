// Thin wrapper over the backend admin API. Calls are prefixed with the app's base path
// (BASE_URL = "/wearable/" in prod, "/" in a plain build) so they survive the host-nginx
// prefix strip; nginx/Vite proxy them to the backend (same-origin, no CORS).

export const apiBase = (import.meta.env.BASE_URL || "/").replace(/\/$/, ""); // e.g. "/wearable"

async function req(path, opts = {}) {
  const res = await fetch(apiBase + path, {
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
  me: () => req("/auth/me"),
  logout: () => req("/auth/logout", { method: "POST" }),

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

  // RBAC management
  listUsers: () => req("/admin/users"),
  createUser: (body) =>
    req("/admin/users", { method: "POST", body: JSON.stringify(body) }),
  deleteUser: (userId) => req(`/admin/users/${userId}`, { method: "DELETE" }),
  listMembers: (studyId) => req(`/admin/studies/${studyId}/members`),
  addMember: (studyId, body) =>
    req(`/admin/studies/${studyId}/members`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  removeMember: (studyId, userId) =>
    req(`/admin/studies/${studyId}/members/${userId}`, { method: "DELETE" }),
};
