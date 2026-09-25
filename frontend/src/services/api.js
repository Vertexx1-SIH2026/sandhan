import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("sandhan_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function saveSession(loginResponse) {
  localStorage.setItem("sandhan_token", loginResponse.access_token);
  localStorage.setItem(
    "sandhan_user",
    JSON.stringify({
      user_id: loginResponse.user_id,
      role: loginResponse.role,
      full_name: loginResponse.full_name,
      assigned_case_ids: loginResponse.assigned_case_ids || [],
    })
  );
}

export function getSession() {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("sandhan_user");
  return raw ? JSON.parse(raw) : null;
}

export function clearSession() {
  localStorage.removeItem("sandhan_token");
  localStorage.removeItem("sandhan_user");
}

export async function login(username, password) {
  const form = new URLSearchParams();
  form.append("username", username);
  form.append("password", password);
  const res = await api.post("/api/v1/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  saveSession(res.data);
  return res.data;
}

export async function getMe() {
  const res = await api.get("/api/v1/auth/me");
  return res.data;
}

export async function getHealth() {
  const res = await api.get("/api/v1/health");
  return res.data;
}

// --- Investigator: upload ---
export async function ingestFiles(caseId, files, declaredType) {
  const form = new FormData();
  form.append("case_id", caseId);
  if (declaredType) form.append("declared_type", declaredType);
  for (const f of files) form.append("files", f);
  const res = await api.post("/api/v1/upload/ingest", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

export async function getJob(jobId) {
  const res = await api.get(`/api/v1/upload/jobs/${jobId}`);
  return res.data;
}

// --- Investigator: graph ---
export async function getIntegratedGraph(caseId, hops) {
  const params = { case_id: caseId };
  if (hops !== undefined && hops !== null) params.hops = hops;
  const res = await api.get("/api/v1/graph/integrated", { params });
  return res.data;
}

export async function searchEntities(caseId, prefix) {
  const res = await api.get("/api/v1/graph/search", { params: { case_id: caseId, prefix } });
  return res.data;
}

export async function escalateEntity(caseId, entityId, reason) {
  const res = await api.post("/api/v1/graph/escalate", { case_id: caseId, entity_id: entityId, reason });
  return res.data;
}

export async function getSubgraph(caseId, centerNode, hops = 2) {
  const res = await api.get("/api/v1/graph/subgraph", {
    params: { case_id: caseId, center_node: centerNode, hops },
  });
  return res.data;
}

// --- Investigator: analytics ---
export async function runRingleaders(caseId) {
  const res = await api.post("/api/v1/analytics/ringleaders", { case_id: caseId });
  return res.data;
}

export async function getSmurfingCycles(caseId, maxDepth = 5, threshold = 50000) {
  const res = await api.get("/api/v1/analytics/smurfing-cycles", {
    params: { case_id: caseId, max_depth: maxDepth, threshold },
  });
  return res.data;
}

export async function predictLinks(caseId) {
  const res = await api.post("/api/v1/analytics/predict-links", { case_id: caseId });
  return res.data;
}

export async function getPendingPredictions(caseId) {
  const res = await api.get("/api/v1/analytics/predicted-links", { params: { case_id: caseId } });
  return res.data;
}

// --- Investigator: historical link discovery ---
export async function getHistoricalLinks(caseId, refresh = false) {
  const res = await api.get("/api/v1/links/historical", { params: { case_id: caseId, refresh } });
  return res.data;
}

export async function decideCaseLink(caseId, otherCaseId, decision) {
  const res = await api.post("/api/v1/links/decide", {
    case_id: caseId, other_case_id: otherCaseId, decision,
  });
  return res.data;
}

// --- Investigator: Act-1 baseline lookup ---
export async function baselineSearch(q) {
  const res = await api.get("/api/v1/baseline/search", { params: { q } });
  return res.data;
}

// --- Investigator: NLP ---
export async function moMatch(caseId, firText, firId) {
  const res = await api.post("/api/v1/nlp/mo-match", { case_id: caseId, fir_text: firText, fir_id: firId });
  return res.data;
}

// --- Investigator: evidence / HITL ---
export async function verifyNode(caseId, sourceId, targetId, score) {
  const res = await api.post("/api/v1/evidence/verify-node", {
    case_id: caseId, source_id: sourceId, target_id: targetId, score,
  });
  return res.data;
}

export async function dismissPrediction(caseId, sourceId, targetId, reason) {
  const res = await api.post("/api/v1/evidence/dismiss-prediction", {
    case_id: caseId, source_id: sourceId, target_id: targetId, reason,
  });
  return res.data;
}

export async function exportEvidencePdf(caseId, pendingNodeIds = []) {
  const res = await api.get("/api/v1/report/evidence-pdf", {
    params: { case_id: caseId, pending_node_ids: pendingNodeIds.join(",") },
    responseType: "blob",
  });
  return res.data; // Blob
}

export async function getCaseAuditLog(caseId) {
  const res = await api.get("/api/v1/investigator/audit-log", { params: { case_id: caseId } });
  return res.data;
}

// --- Admin ---
export async function listUsers() {
  const res = await api.get("/api/v1/admin/users");
  return res.data;
}

export async function createUser(payload) {
  const res = await api.post("/api/v1/admin/users", payload);
  return res.data;
}

export async function assignCase(userId, caseId) {
  const res = await api.post(`/api/v1/admin/users/${userId}/assign-case`, { case_id: caseId });
  return res.data;
}

export async function getSystemAuditLog() {
  const res = await api.get("/api/v1/admin/audit-log");
  return res.data;
}
