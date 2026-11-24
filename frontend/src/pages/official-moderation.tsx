import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  Clock3,
  FileSearch,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { ApiError } from '@/lib/api';
import { SanctionHistory } from '@/components/sanction-history';
import { DashboardLayout } from '@/components/dashboard-layout';
import {
  getOfficialAnalysis,
  getOfficialReport,
  listOfficialReports,
  submitOfficialDecision,
  submitOfficialTriage,
  type ModerationHumanDecisionPayload,
  type ModerationAnalysisSummary,
  type ModerationReportDetail,
  type ModerationReportPage,
} from '@/services/official-moderation-api';

const PAGE_SIZE = 20;
const DECISION_OPTIONS = [
  ['NO_VIOLATION', 'Sem violação'],
  ['REVIEWED_MANUALLY', 'Revisada sem sanção'],
  ['WARNING', 'Advertência'],
  ['TEMPORARY_SUSPENSION', 'Suspensão temporária (7 dias)'],
  ['PERMANENT_BAN', 'Banimento permanente'],
] as const;

function dateTime(value: string | null | undefined) {
  if (!value) return 'Não disponível';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Não disponível'
    : new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 403) return 'Acesso restrito à equipe oficial ativa da plataforma.';
    if (error.status === 401) return 'Sua sessão não é mais válida. Entre novamente.';
    if (error.status === 404) return 'A denúncia não foi encontrada.';
    return error.message;
  }
  return fallback;
}

function isAuthorizationError(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

function StatusBadge({ value }: { value: string }) {
  return <span className="moderation-status">{value}</span>;
}

function AnalysisPanel({ analysis }: { analysis: ModerationAnalysisSummary }) {
  const categories = Object.entries(analysis.categories ?? {});
  const scores = Object.entries(analysis.category_scores ?? {});
  const inputTypes = Object.entries(analysis.category_applied_input_types ?? {});

  return (
    <section className="moderation-card" aria-labelledby="analysis-title">
      <header className="moderation-card__heading">
        <div><span className="moderation-card__icon"><FileSearch size={16} /></span><div><h3 id="analysis-title">Resultado da análise</h3><p>Classificação retornada pelo provedor</p></div></div>
        <StatusBadge value={analysis.status} />
      </header>
      <div className="moderation-analysis-summary">
        <div><span>Modelo</span><strong>{analysis.model ?? 'Não disponível'}</strong></div>
        <div><span>Resultado geral</span><strong>{analysis.flagged === null ? 'Não disponível' : analysis.flagged ? 'Sinalizada pelo provedor' : 'Não sinalizada pelo provedor'}</strong></div>
        <div><span>Tentativas</span><strong>{analysis.attempt_count}</strong></div>
        <div><span>Analisada em</span><strong>{dateTime(analysis.analyzed_at)}</strong></div>
      </div>

      {analysis.last_error_code && <p className="moderation-inline-warning"><AlertCircle size={14} /> Código de falha: {analysis.last_error_code}</p>}

      <div className="moderation-analysis-tables">
        <section><h4>Categorias</h4>{categories.length ? <dl>{categories.map(([name, flagged]) => <div key={name}><dt>{name}</dt><dd>{flagged ? 'Sinalizada' : 'Não sinalizada'}</dd></div>)}</dl> : <p>Sem categorias disponíveis.</p>}</section>
        <section><h4>Pontuações</h4>{scores.length ? <dl>{scores.map(([name, score]) => <div key={name}><dt>{name}</dt><dd>{score}</dd></div>)}</dl> : <p>Sem pontuações disponíveis.</p>}</section>
      </div>

      {inputTypes.length > 0 && <details className="moderation-input-types"><summary>Tipos de entrada aplicados</summary><dl>{inputTypes.map(([name, values]) => <div key={name}><dt>{name}</dt><dd>{values.join(', ') || 'Nenhum'}</dd></div>)}</dl></details>}
      <p className="moderation-note">A análise apresenta classificação e pontuações do provedor. Ela não aplica punições nem substitui a decisão humana.</p>
    </section>
  );
}

export function OfficialModerationPage() {
  const [pageNumber, setPageNumber] = useState(1);
  const [queue, setQueue] = useState<ModerationReportPage | null>(null);
  const [queueLoading, setQueueLoading] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selectedIdRef = useRef<number | null>(selectedId);
  selectedIdRef.current = selectedId;
  const [report, setReport] = useState<ModerationReportDetail | null>(null);
  const [analysis, setAnalysis] = useState<ModerationAnalysisSummary | null>(null);
  const [loadedReportId, setLoadedReportId] = useState<number | null>(null);
  const detailRequestSequence = useRef(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [triageChoice, setTriageChoice] = useState<boolean | null>(null);
  const [triageReason, setTriageReason] = useState('');
  const [sensitiveContentSuspected, setSensitiveContentSuspected] = useState(false);
  const [confirmExternalAnalysis, setConfirmExternalAnalysis] = useState(false);
  const [triageSubmitting, setTriageSubmitting] = useState(false);
  const [decisionLabel, setDecisionLabel] = useState<ModerationHumanDecisionPayload['decision'] | ''>('');
  const [decisionReason, setDecisionReason] = useState('');
  const [decisionSubmitting, setDecisionSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((queue?.total ?? 0) / PAGE_SIZE)),
    [queue?.total],
  );

  const loadQueue = useCallback(async (requestedPage: number) => {
    setQueueLoading(true);
    setQueueError(null);
    try {
      const result = await listOfficialReports(requestedPage, PAGE_SIZE);
      setQueue(result);
      setSelectedId((current) => {
        if (current !== null && result.items.some((item) => item.id === current)) return current;
        return result.items[0]?.id ?? null;
      });
    } catch (error) {
      if (isAuthorizationError(error)) {
        setQueue(null);
        setSelectedId(null);
        setReport(null);
        setAnalysis(null);
        setLoadedReportId(null);
      }
      setQueueError(errorMessage(error, 'Não foi possível carregar a fila de denúncias.'));
    } finally {
      setQueueLoading(false);
    }
  }, []);

  const loadSelectedReport = useCallback(async (reportId: number) => {
    const requestSequence = ++detailRequestSequence.current;
    setDetailLoading(true);
    setDetailError(null);
    setReport(null);
    setAnalysis(null);
    setLoadedReportId(null);
    try {
      const [detail, currentAnalysis] = await Promise.all([
        getOfficialReport(reportId),
        getOfficialAnalysis(reportId),
      ]);
      if (requestSequence !== detailRequestSequence.current || detail.id !== reportId) return;
      setReport(detail);
      setAnalysis(currentAnalysis);
      setLoadedReportId(reportId);
    } catch (error) {
      if (requestSequence !== detailRequestSequence.current) return;
      if (isAuthorizationError(error)) {
        setReport(null);
        setAnalysis(null);
        setLoadedReportId(null);
        setQueue(null);
        setSelectedId(null);
      }
      setDetailError(errorMessage(error, 'Não foi possível carregar os detalhes da denúncia.'));
    } finally {
      if (requestSequence === detailRequestSequence.current) setDetailLoading(false);
    }
  }, []);

  useEffect(() => { void loadQueue(pageNumber); }, [loadQueue, pageNumber]);
  useEffect(() => {
    if (selectedId === null) {
      detailRequestSequence.current += 1;
      setReport(null);
      setAnalysis(null);
      setLoadedReportId(null);
      setDetailLoading(false);
      setDetailError(null);
      return;
    }
    setReport(null);
    setAnalysis(null);
    setTriageChoice(null);
    setTriageReason('');
    setSensitiveContentSuspected(false);
    setConfirmExternalAnalysis(false);
    setDecisionLabel('');
    setDecisionReason('');
    setActionError(null);
    setNotice(null);
    void loadSelectedReport(selectedId);
  }, [loadSelectedReport, selectedId]);

  async function refreshCurrent(reportId: number) {
    if (selectedIdRef.current === reportId) await loadSelectedReport(reportId);
    await loadQueue(pageNumber);
  }

  async function handleTriage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reportId = report?.id;
    if (reportId === undefined || reportId !== selectedId || loadedReportId !== reportId || triageChoice === null) return;
    const reason = triageReason.trim();
    if (!reason || reason.length > 1000 || (triageChoice && !confirmExternalAnalysis)) return;

    setTriageSubmitting(true);
    setActionError(null);
    setNotice(null);
    try {
      await submitOfficialTriage(reportId, {
        external_analysis_eligible: triageChoice,
        sensitive_content_suspected: sensitiveContentSuspected,
        reason,
      });
      if (selectedIdRef.current === reportId) {
        setNotice(triageChoice
          ? 'Triagem registrada. O snapshot aprovado foi liberado para análise externa.'
          : 'Triagem registrada. A denúncia foi mantida para revisão manual.');
      }
      await refreshCurrent(reportId);
    } catch (error) {
      if (selectedIdRef.current === reportId) setActionError(errorMessage(error, 'Não foi possível registrar a triagem.'));
    } finally {
      setTriageSubmitting(false);
    }
  }

  async function handleDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reportId = report?.id;
    if (reportId === undefined || reportId !== selectedId || loadedReportId !== reportId) return;
    const decision = decisionLabel;
    const reason = decisionReason.trim();
    if (!decision || decision.length > 50 || !reason || reason.length > 1000) return;

    const label = DECISION_OPTIONS.find(([code]) => code === decision)?.[1];
    if (!window.confirm(`Registrar “${label}” na denúncia #${reportId}?`)) return;
    setDecisionSubmitting(true);
    setActionError(null);
    setNotice(null);
    try {
      await submitOfficialDecision(reportId, { decision, reason });
      if (selectedIdRef.current === reportId) {
        setNotice('Decisão humana e sanções aplicáveis registradas no histórico da denúncia.');
      }
      await refreshCurrent(reportId);
    } catch (error) {
      if (selectedIdRef.current === reportId) setActionError(errorMessage(error, 'Não foi possível registrar a decisão.'));
    } finally {
      setDecisionSubmitting(false);
    }
  }

  const activeReport = report?.id === selectedId && loadedReportId === selectedId ? report : null;
  const activeAnalysis = activeReport ? analysis : null;
  const canTriage = activeReport?.status === 'PENDING'
    && activeReport.triage_status === 'PENDING'
    && activeAnalysis?.status === 'PENDING_TRIAGE';
  const canDecide = activeReport?.status === 'PENDING';

  return (
    <DashboardLayout title="Moderação oficial" description="Fila de denúncias e revisão humana da plataforma.">
      <section className="moderation-page" aria-label="Painel oficial de moderação">
        <aside className="moderation-queue" aria-label="Fila de denúncias">
          <header className="moderation-queue__header">
            <div><span className="moderation-eyebrow">EQUIPE OFICIAL</span><h2>Denúncias</h2><p>{queue ? `${queue.total} registros` : 'Fila protegida'}</p></div>
            <button className="moderation-icon-button" type="button" onClick={() => void loadQueue(pageNumber)} aria-label="Atualizar fila" disabled={queueLoading}><RefreshCw size={15} className={queueLoading ? 'spin' : ''} /></button>
          </header>

          {queueError ? (
            <div className="moderation-state moderation-state--error" role="alert"><ShieldAlert size={21} /><strong>{queueError}</strong>{queueError.includes('equipe oficial') ? <p>O backend não autorizou este usuário. Nenhum dado oficial foi disponibilizado.</p> : <button type="button" onClick={() => void loadQueue(pageNumber)}>Tentar novamente</button>}</div>
          ) : queueLoading ? (
            <div className="moderation-state" role="status"><LoaderCircle className="spin" size={20} /><span>Carregando fila…</span></div>
          ) : queue?.items.length ? (
            <>
              <div className="moderation-queue__items">
                {queue.items.map((item) => (
                  <button key={item.id} type="button" className={`moderation-queue-item${selectedId === item.id ? ' is-selected' : ''}`} onClick={() => setSelectedId(item.id)} aria-current={selectedId === item.id ? 'true' : undefined}>
                    <span className="moderation-queue-item__top"><strong>Denúncia #{item.id}</strong><time dateTime={item.created_at}>{dateTime(item.created_at)}</time></span>
                    <span className="moderation-queue-item__message">Mensagem #{item.message_id}</span>
                    <span className="moderation-queue-item__reason">{item.reason}</span>
                    <span className="moderation-queue-item__statuses"><StatusBadge value={item.status} /><StatusBadge value={item.analysis.status} /></span>
                  </button>
                ))}
              </div>
              <footer className="moderation-pagination">
                <button type="button" onClick={() => setPageNumber((current) => Math.max(1, current - 1))} disabled={pageNumber <= 1 || queueLoading} aria-label="Página anterior"><ArrowLeft size={15} /></button>
                <span>Página {queue.page} de {totalPages}</span>
                <button type="button" onClick={() => setPageNumber((current) => Math.min(totalPages, current + 1))} disabled={pageNumber >= totalPages || queueLoading} aria-label="Próxima página"><ArrowRight size={15} /></button>
              </footer>
            </>
          ) : (
            <div className="moderation-state moderation-state--empty"><ShieldCheck size={22} /><strong>Fila vazia</strong><p>Não há denúncias nesta página.</p></div>
          )}
        </aside>

        <section className="moderation-detail" aria-label="Detalhes da denúncia selecionada">
          {notice && <div className="moderation-notice" role="status"><Check size={15} />{notice}</div>}
          {actionError && <div className="moderation-action-error" role="alert"><AlertCircle size={15} />{actionError}</div>}
          {detailLoading ? (
            <div className="moderation-detail-state" role="status"><LoaderCircle className="spin" size={22} /><span>Carregando denúncia e análise…</span></div>
          ) : detailError ? (
            <div className="moderation-detail-state moderation-detail-state--error" role="alert"><AlertCircle size={22} /><strong>{detailError}</strong></div>
          ) : activeReport && activeAnalysis ? (
            <div className="moderation-detail__content">
              <header className="moderation-report-heading">
                <div><span className="moderation-eyebrow">REVISÃO DE DENÚNCIA</span><h2>Denúncia #{activeReport.id}</h2><p>Recebida em {dateTime(activeReport.created_at)} · mensagem #{activeReport.message_id}</p></div>
                <button className="moderation-icon-button" type="button" onClick={() => void loadSelectedReport(activeReport.id)} aria-label="Atualizar detalhes"><RefreshCw size={15} /></button>
              </header>

              <section className="moderation-card">
                <header className="moderation-card__heading"><div><span className="moderation-card__icon"><UserRound size={16} /></span><div><h3>Registro da denúncia</h3><p>Identificadores conforme retornados pela API</p></div></div><StatusBadge value={activeReport.status} /></header>
                <div className="moderation-report-facts">
                  <div><span>Denunciante</span><strong>Usuário #{activeReport.reporter_id}</strong></div>
                  <div><span>Autor da mensagem</span><strong>Usuário #{activeReport.evidence.message_author_id}</strong></div>
                  {activeReport.evidence.channel_id != null && <div><span>Origem da mensagem</span>
                    <strong>Servidor #{activeReport.evidence.server_id} · Canal #{activeReport.evidence.channel_id}</strong></div>}
                  <div><span>Status de triagem</span><StatusBadge value={activeReport.triage_status} /></div>
                  <div><span>Mensagem denunciada</span><strong>#{activeReport.evidence.message_id}</strong></div>
                </div>
                <div className="moderation-reason"><span>Motivo informado</span><p>{activeReport.reason}</p></div>
              </section>

              <section className="moderation-card moderation-evidence" aria-labelledby="evidence-title">
                <header className="moderation-card__heading"><div><span className="moderation-card__icon moderation-card__icon--evidence"><FileSearch size={16} /></span><div><h3 id="evidence-title">Evidência da mensagem</h3><p>Snapshot histórico registrado na denúncia</p></div></div><span className="moderation-evidence__private"><ShieldCheck size={13} /> Equipe oficial</span></header>
                <blockquote>{activeReport.evidence.content_snapshot}</blockquote>
                <dl className="moderation-evidence__metadata">
                  <div><dt>Enviada em</dt><dd>{dateTime(activeReport.evidence.message_created_at)}</dd></div>
                  <div><dt>Atualizada em</dt><dd>{dateTime(activeReport.evidence.message_updated_at)}</dd></div>
                  <div><dt>Editada em</dt><dd>{dateTime(activeReport.evidence.message_edited_at)}</dd></div>
                  <div><dt>Snapshot capturado</dt><dd>{dateTime(activeReport.evidence.captured_at)}</dd></div>
                </dl>
              </section>

              <AnalysisPanel analysis={activeAnalysis} />
              <SanctionHistory key={activeReport.id} targetId={activeReport.evidence.message_author_id} />

              <section className="moderation-card" aria-labelledby="actions-title">
                <header className="moderation-card__heading"><div><span className="moderation-card__icon moderation-card__icon--history"><Clock3 size={16} /></span><div><h3 id="actions-title">Histórico de ações</h3><p>Ações auditáveis registradas nesta denúncia</p></div></div></header>
                {activeReport.actions.length ? <ol className="moderation-action-list">{activeReport.actions.map((action) => <li key={action.id}><span className="moderation-action-list__marker" /><div><strong>{action.action_type}</strong><p>{action.reason || 'Sem justificativa informada.'}</p><span>Responsável: usuário #{action.actor_user_id} · {dateTime(action.created_at)}</span></div></li>)}</ol> : <p className="moderation-card__empty-copy">Nenhuma ação registrada.</p>}
              </section>

              {canTriage && (
                <section className="moderation-card moderation-form-card" aria-labelledby="triage-title">
                  <header className="moderation-card__heading"><div><span className="moderation-card__icon"><ShieldCheck size={16} /></span><div><h3 id="triage-title">Triagem humana</h3><p>Defina se o snapshot pode seguir para análise externa.</p></div></div></header>
                  <p className="moderation-note">Autorizar envia apenas o snapshot desta mensagem ao provedor. Suspeitas de exploração sexual infantil devem permanecer em análise humana e nunca ser enviadas à API. A classificação não aplica punições.</p>
                  <form onSubmit={handleTriage}>
                    <div className="moderation-choice-row" role="group" aria-label="Elegibilidade para análise externa">
                      <button type="button" className={triageChoice === true ? 'is-chosen' : ''} onClick={() => setTriageChoice(true)} disabled={sensitiveContentSuspected}>Autorizar análise externa</button>
                      <button type="button" className={triageChoice === false ? 'is-chosen' : ''} onClick={() => { setTriageChoice(false); setConfirmExternalAnalysis(false); }}>Manter para análise manual</button>
                    </div>
                    <label className="moderation-confirm"><input type="checkbox" checked={sensitiveContentSuspected} onChange={(event) => { const suspected = event.target.checked; setSensitiveContentSuspected(suspected); if (suspected) { setTriageChoice(false); setConfirmExternalAnalysis(false); } }} /><span>Há suspeita de conteúdo de exploração sexual infantil; manter sob revisão humana e bloquear envio externo.</span></label>
                    {sensitiveContentSuspected && <p className="moderation-inline-warning"><AlertCircle size={14} /> A suspeita ficará registrada na auditoria. Nenhum classificador automático será usado para esse conteúdo.</p>}
                    <label htmlFor="triage-reason">Justificativa da triagem <span>obrigatória nesta interface</span></label>
                    <textarea id="triage-reason" value={triageReason} onChange={(event) => setTriageReason(event.target.value)} maxLength={1000} rows={3} required />
                    <div className="moderation-form__counter">{triageReason.length} / 1.000</div>
                    {triageChoice === true && <label className="moderation-confirm"><input type="checkbox" checked={confirmExternalAnalysis} onChange={(event) => setConfirmExternalAnalysis(event.target.checked)} /><span>Confirmo que o snapshot pode ser enviado à análise externa.</span></label>}
                    <button className="moderation-submit" type="submit" disabled={triageChoice === null || !triageReason.trim() || (triageChoice && !confirmExternalAnalysis) || triageSubmitting}>{triageSubmitting ? 'Registrando triagem…' : 'Registrar triagem'}</button>
                  </form>
                </section>
              )}

              {canDecide && (
                <section className="moderation-card moderation-form-card" aria-labelledby="decision-title">
                  <header className="moderation-card__heading"><div><span className="moderation-card__icon moderation-card__icon--history"><Check size={16} /></span><div><h3 id="decision-title">Registrar decisão humana</h3><p>A decisão ficará vinculada ao responsável e ao histórico.</p></div></div></header>
                  <p className="moderation-note">Advertências válidas são acumuladas. A segunda gera suspensão por 7 dias e a terceira gera banimento permanente.</p>
                  <form onSubmit={handleDecision}>
                    <label htmlFor="decision-label">Decisão</label>
                    <select id="decision-label" value={decisionLabel} onChange={(event) => setDecisionLabel(event.target.value as ModerationHumanDecisionPayload['decision'] | '')} required>
                      <option value="">Selecione uma decisão</option>
                      {DECISION_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    <label htmlFor="decision-reason">Justificativa <span>obrigatória · até 1.000 caracteres</span></label>
                    <textarea id="decision-reason" value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={1000} rows={3} required />
                    <div className="moderation-form__counter">{decisionReason.length} / 1.000</div>
                    <button className="moderation-submit" type="submit" disabled={!decisionLabel.trim() || !decisionReason.trim() || decisionSubmitting}>{decisionSubmitting ? 'Registrando decisão…' : 'Registrar decisão'}</button>
                  </form>
                </section>
              )}
            </div>
          ) : queueError ? (
            <div className="moderation-detail-state moderation-detail-state--empty"><ShieldCheck size={24} /><strong>Dados oficiais protegidos</strong><p>A resposta do backend determina se este usuário pode acessar a fila.</p></div>
          ) : (
            <div className="moderation-detail-state moderation-detail-state--empty"><FileSearch size={24} /><strong>{queueLoading ? 'Carregando fila oficial' : queue?.total ? 'Selecione uma denúncia' : 'Nenhuma denúncia disponível'}</strong><p>{queueLoading ? 'Buscando registros autorizados…' : queue?.total ? 'Escolha um item da fila para consultar os detalhes.' : 'Não há denúncias registradas.'}</p></div>
          )}
        </section>
      </section>
    </DashboardLayout>
  );
}
