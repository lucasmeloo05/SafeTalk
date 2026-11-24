import { api } from '@/lib/api';

export type ModerationAnalysisSummary = {
  status: string;
  attempt_count: number;
  model: string | null;
  flagged: boolean | null;
  categories: Record<string, boolean> | null;
  category_scores: Record<string, number> | null;
  category_applied_input_types: Record<string, string[]> | null;
  provider_response_id: string | null;
  analyzed_at: string | null;
  last_error_code: string | null;
  updated_at: string;
};

export type ModerationReportQueueItem = {
  id: number;
  message_id: number;
  reason: string;
  status: string;
  triage_status: string;
  analysis: ModerationAnalysisSummary;
  created_at: string;
};

export type ModerationReportPage = {
  items: ModerationReportQueueItem[];
  page: number;
  page_size: number;
  total: number;
};

export type ModerationReportEvidence = {
  message_id: number;
  message_author_id: number;
  server_id?: number | null;
  channel_id?: number | null;
  content_snapshot: string;
  message_created_at: string;
  message_updated_at: string;
  message_edited_at: string | null;
  captured_at: string;
};

export type ModerationAction = {
  id: number;
  actor_user_id: number;
  action_type: string;
  decision_code?: string | null;
  reason: string | null;
  created_at: string;
};

export type ModerationReportDetail = {
  id: number;
  message_id: number;
  reporter_id: number;
  reason: string;
  status: string;
  triage_status: string;
  created_at: string;
  updated_at: string;
  evidence: ModerationReportEvidence;
  analysis: ModerationAnalysisSummary;
  actions: ModerationAction[];
};

export type ModerationTriagePayload = {
  external_analysis_eligible: boolean;
  sensitive_content_suspected: boolean;
  reason: string;
};

export type ModerationHumanDecisionPayload = {
  decision: 'NO_VIOLATION' | 'REVIEWED_MANUALLY' | 'WARNING' | 'TEMPORARY_SUSPENSION' | 'PERMANENT_BAN';
  reason: string;
};

export type ModerationSanction = {
  id: number;
  report_id: number;
  target_user_id: number;
  actor_user_id: number;
  sanction_type: 'WARNING' | 'TEMPORARY_SUSPENSION' | 'PERMANENT_BAN';
  reason: string;
  issued_at: string;
  expires_at: string | null;
  reversed_at: string | null;
  reversed_by: number | null;
  reversal_reason: string | null;
  requires_review: boolean;
  basis_warning_ids: number[];
  review_history: Array<{
    id: number;
    actor_user_id: number;
    review_type: 'REVIEW_REQUIRED' | 'UPHELD' | 'REVERSED';
    reason: string;
    created_at: string;
  }>;
};

export type ModerationDecisionResponse = {
  id: number;
  report_id: number;
  actor_user_id: number;
  decision: string;
  reason: string;
  created_at: string;
  sanctions: ModerationSanction[];
};

export async function listOfficialReports(page = 1, pageSize = 20) {
  const response = await api.get<ModerationReportPage>('/official/reports', {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

export async function getOfficialReport(reportId: number) {
  const response = await api.get<ModerationReportDetail>(`/official/reports/${reportId}`);
  return response.data;
}

export async function getOfficialAnalysis(reportId: number) {
  const response = await api.get<ModerationAnalysisSummary>(`/official/reports/${reportId}/analysis`);
  return response.data;
}

export async function submitOfficialTriage(reportId: number, payload: ModerationTriagePayload) {
  const response = await api.post<ModerationAnalysisSummary>(
    `/official/reports/${reportId}/triage`,
    payload,
  );
  return response.data;
}

export async function submitOfficialDecision(
  reportId: number,
  payload: ModerationHumanDecisionPayload,
) {
  const response = await api.post<ModerationDecisionResponse>(
    `/official/reports/${reportId}/decision`,
    payload,
  );
  return response.data;
}

export type SanctionReviewDecision = 'REVERSE' | 'UPHOLD';

export async function listOfficialSanctions(targetId: number, page: number, signal: AbortSignal) {
  const response = await api.get<{ items: ModerationSanction[]; total: number }>('/official/sanctions', {
    params: { target_user_id: targetId, page, page_size: 10 }, signal,
  });
  return response.data;
}

export async function reviewOfficialSanction(id: number, decision: SanctionReviewDecision, reason: string) {
  const response = await api.post<ModerationSanction>(`/official/sanctions/${id}/review`, { decision, reason });
  return response.data;
}
