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
  updateStudy: (studyId, body) =>
    req(`/admin/studies/${studyId}`, { method: "PATCH", body: JSON.stringify(body) }),
  listSubjects: (studyId) => req(`/admin/studies/${studyId}/subjects`),
  createSubject: (studyId, body) =>
    req(`/admin/studies/${studyId}/subjects`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateSubject: (subjectId, body) =>
    req(`/admin/subjects/${subjectId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteSubject: (subjectId) => req(`/admin/subjects/${subjectId}`, { method: "DELETE" }),
  addRegistration: (subjectId, provider) =>
    req(`/admin/subjects/${subjectId}/registrations`, {
      method: "POST",
      body: JSON.stringify({ provider }),
    }),
  deleteRegistration: (subjectId, registrationId) =>
    req(`/admin/subjects/${subjectId}/registrations/${registrationId}`, { method: "DELETE" }),
  daily: (subjectId) => req(`/admin/subjects/${subjectId}/daily`),
  dayPoints: (subjectId, day) =>
    req(`/admin/subjects/${subjectId}/daily/${day}/points`),
  devices: (subjectId) => req(`/admin/subjects/${subjectId}/devices`),
  exportSubject: (subjectId, start, end) => {
    const q = new URLSearchParams();
    if (start) q.set("start", start);
    if (end) q.set("end", end);
    const qs = q.toString();
    return req(`/admin/subjects/${subjectId}/export${qs ? "?" + qs : ""}`);
  },
  exportStudy: (studyId, start, end) => {
    const q = new URLSearchParams();
    if (start) q.set("start", start);
    if (end) q.set("end", end);
    const qs = q.toString();
    return req(`/admin/studies/${studyId}/export${qs ? "?" + qs : ""}`);
  },
  consolidate: (subjectId, start, end) =>
    req(`/admin/subjects/${subjectId}/consolidate?start=${start}&end=${end}`, {
      method: "POST",
    }),
  backfill: (subjectId, start, end) =>
    req(`/admin/subjects/${subjectId}/backfill?start=${start}&end=${end}`, {
      method: "POST",
    }),
  reprocess: (subjectId) =>
    req(`/admin/subjects/${subjectId}/reprocess`, { method: "POST" }),
  revoke: (subjectId, provider) =>
    req(
      `/admin/subjects/${subjectId}/revoke${provider ? `?provider=${provider}` : ""}`,
      { method: "POST" },
    ),

  // RBAC management
  listUsers: () => req("/admin/users"),
  createUser: (body) =>
    req("/admin/users", { method: "POST", body: JSON.stringify(body) }),
  deleteUser: (userId) => req(`/admin/users/${userId}`, { method: "DELETE" }),
  listMembers: (studyId) => req(`/admin/studies/${studyId}/members`),
  assignableUsers: (studyId) => req(`/admin/studies/${studyId}/assignable-users`),
  addMember: (studyId, body) =>
    req(`/admin/studies/${studyId}/members`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  removeMember: (studyId, userId) =>
    req(`/admin/studies/${studyId}/members/${userId}`, { method: "DELETE" }),

  // Google credential sets (superuser only)
  listCredentialSets: () => req("/admin/credential-sets"),
  createCredentialSet: (body) =>
    req("/admin/credential-sets", { method: "POST", body: JSON.stringify(body) }),
  updateCredentialSet: (setId, body) =>
    req(`/admin/credential-sets/${setId}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteCredentialSet: (setId) =>
    req(`/admin/credential-sets/${setId}`, { method: "DELETE" }),
  setStudyCredentialSet: (studyId, credentialSetId) =>
    req(`/admin/studies/${studyId}/credential-set`, {
      method: "PUT",
      body: JSON.stringify({ credential_set_id: credentialSetId }),
    }),
};
