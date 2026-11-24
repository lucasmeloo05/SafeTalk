import { useEffect, useState } from 'react';
import { ApiError } from '@/lib/api';
import { listOfficialSanctions, reviewOfficialSanction, type ModerationSanction, type SanctionReviewDecision } from '@/services/official-moderation-api';

const labels = { WARNING: 'Advertência', TEMPORARY_SUSPENSION: 'Suspensão temporária', PERMANENT_BAN: 'Banimento permanente' };
const reviews = { REVIEW_REQUIRED: 'Revisão solicitada', UPHELD: 'Sanção mantida', REVERSED: 'Sanção revertida' };
const date = (value: string) => new Date(value).toLocaleString('pt-BR');

function failure(error: unknown) {
  if (error instanceof ApiError && error.status === 403) return 'Sem permissão para consultar ou revisar sanções.';
  if (error instanceof ApiError && error.status === 401) return 'Sessão expirada. Entre novamente.';
  return error instanceof ApiError ? error.message : 'Não foi possível carregar ou atualizar o histórico.';
}

export function SanctionHistory({ targetId }: { targetId: number }) {
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof listOfficialSanctions>> | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState<{ id: number; decision: SanctionReviewDecision } | null>(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    const controller = new AbortController();
    listOfficialSanctions(targetId, page, controller.signal).then(result => {
      if (!controller.signal.aborted) { setData(result); setNow(Date.now()); }
    }).catch(err => { if (!controller.signal.aborted) setError(failure(err)); });
    return () => controller.abort();
  }, [targetId, page, reload]);

  useEffect(() => {
    const upcoming = data?.items.flatMap(s => s.expires_at ? [Date.parse(s.expires_at)] : []).filter(t => t > now);
    if (!upcoming?.length) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(1, Math.min(...upcoming) - Date.now()));
    return () => window.clearTimeout(timer);
  }, [data, now]);

  function load(next: number) {
    setData(null); setError(''); setForm(null); setReason(''); setPage(next); setReload(n => n + 1);
  }

  function open(item: ModerationSanction, decision: SanctionReviewDecision) {
    setForm({ id: item.id, decision }); setReason(''); setError(''); setNotice('');
  }

  async function submit() {
    if (!form || saving || !reason.trim()) return;
    const verb = form.decision === 'REVERSE' ? 'reverter' : 'manter';
    if (!window.confirm(`Confirma ${verb} a sanção #${form.id} do usuário #${targetId}?`)) return;
    setSaving(true);
    try {
      await reviewOfficialSanction(form.id, form.decision, reason.trim());
      setNotice('Revisão registrada.'); load(page);
    } catch (err) {
      setError(failure(err));
      if (err instanceof ApiError && [401, 403, 409].includes(err.status ?? 0)) { setData(null); setForm(null); }
    } finally { setSaving(false); }
  }

  return <section className="moderation-card moderation-form-card sanction-history" aria-label="Histórico de sanções">
    <h3>Histórico de sanções · usuário #{targetId}</h3>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error} <button disabled={saving} onClick={() => load(page)}>Atualizar histórico</button></p>}
    {!data && !error && <p role="status">Carregando sanções…</p>}
    {data && <>
      {!data.items.length && <p>Nenhuma sanção nesta página.</p>}
      <ol className="moderation-action-list">{data.items.map(item => {
        const expired = item.expires_at && Date.parse(item.expires_at) <= now;
        const state = item.reversed_at ? 'Revertida' : expired ? 'Expirada' : 'Vigente';
        return <li key={item.id}><div>
          <strong>{labels[item.sanction_type]} #{item.id}</strong> <span className="moderation-status">{state}</span>
          {item.requires_review && <strong> · Aguardando revisão</strong>}
          <p>{item.reason}</p>
          <span>{date(item.issued_at)} · Responsável #{item.actor_user_id} · Denúncia #{item.report_id}</span>
          {item.expires_at && <p>Término da suspensão: {date(item.expires_at)}</p>}
          {!!item.basis_warning_ids.length && <p>Advertências de origem: {item.basis_warning_ids.map(id => '#' + id).join(', ')}</p>}
          {item.review_history.map(r => <p key={r.id}>{reviews[r.review_type]} · {date(r.created_at)} · Responsável #{r.actor_user_id} · {r.reason}</p>)}
          {!item.reversed_at && <div><button disabled={saving} onClick={() => open(item, 'REVERSE')}>Reverter sanção #{item.id}</button>
            {item.requires_review && <button disabled={saving} onClick={() => open(item, 'UPHOLD')}>Manter sanção #{item.id}</button>}</div>}
          {form?.id === item.id && <form onSubmit={e => { e.preventDefault(); void submit(); }}>
            <label>Justificativa da revisão<textarea required maxLength={1000} value={reason} disabled={saving} onChange={e => setReason(e.target.value)} /></label>
            <button disabled={saving || !reason.trim()} className="moderation-submit">{form.decision === 'REVERSE' ? 'Confirmar reversão' : 'Confirmar manutenção'}</button>
            <button type="button" disabled={saving} onClick={() => setForm(null)}>Cancelar</button>
          </form>}
        </div></li>;
      })}</ol>
      {(page > 1 || data.total > 10) && <nav aria-label="Páginas de sanções">
        <button disabled={saving || page === 1} onClick={() => load(page - 1)}>Anterior</button> Página {page} <button disabled={saving || page * 10 >= data.total} onClick={() => load(page + 1)}>Próxima</button>
      </nav>}
    </>}
  </section>;
}
