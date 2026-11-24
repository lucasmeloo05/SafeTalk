import { useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api';
import { channelApi, type Channel, type ChannelChange } from '@/services/channel-api';
import { type MessageResponse } from '@/services/conversation-api';
import { MESSAGE_POLL_INTERVAL_MS } from '@/services/message-timing';

function errorText(cause: unknown) {
  return cause instanceof Error ? cause.message : 'Não foi possível concluir a solicitação.';
}

export function ServerChannels({ serverId, userId, owner }: { serverId: number; userId: number; owner: boolean }) {
  const [open, setOpen] = useState(false);
  return <section className="server-panel"><header className="server-panel__header"><h3>Canais do servidor</h3>
    <button className="server-secondary-button" onClick={() => setOpen(!open)}>{open ? 'Fechar canais' : 'Abrir canais'}</button></header>
    {open && <ChannelPicker key={serverId} serverId={serverId} userId={userId} owner={owner} />}
  </section>;
}

function ChannelPicker({ serverId, userId, owner }: { serverId: number; userId: number; owner: boolean }) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selected, select] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    channelApi.list(serverId, offset, controller.signal).then(page => {
      if (controller.signal.aborted) return;
      setChannels(current => offset === 0 ? page : [...current, ...page.filter(c => !current.some(old => old.id === c.id))]);
      setMore(page.length === 50);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [serverId, offset, retry]);
  const channel = channels.find(c => c.id === selected);
  return <div className="channel-workspace"><label className="server-field">Selecionar canal <select value={selected ?? ''} onChange={e => select(Number(e.target.value) || null)}>
    <option value="">Selecione um canal</option>{channels.map(c => <option key={c.id} value={c.id}>{c.name}{c.is_private ? ' · privado' : ''}</option>)}
  </select></label>
    {loading && <p role="status">Carregando canais…</p>}
    {error && <p role="alert">{error} <button className="server-secondary-button" onClick={() => setRetry(n => n + 1)}>Tentar carregar canais novamente</button></p>}
    {!loading && !error && !channels.length && <p>Nenhum canal disponível.</p>}
    {more && !error && <button className="server-secondary-button" disabled={loading} onClick={() => setOffset(n => n + 50)}>Mais canais</button>}
    {channel && <ChannelChat key={channel.id} channel={channel} userId={userId} owner={owner}
      onPolicy={updated => setChannels(all => all.map(c => c.id === updated.id ? updated : c))} />}
  </div>;
}

type Row = ChannelChange;
type Action = { kind: 'edit' | 'remove' | 'report'; message: MessageResponse };
function ChannelChat({ channel, userId, owner, onPolicy }: {
  channel: Channel; userId: number; owner: boolean; onPolicy: (updated: Channel) => void;
}) {
  const sid = channel.server_id, cid = channel.id;
  const [rows, setRows] = useState<Row[]>([]);
  const [canPublish, setCanPublish] = useState(false);
  const [ready, setReady] = useState(false);
  const [more, setMore] = useState(false);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [readError, setReadError] = useState('');
  const [feedback, setFeedback] = useState('');
  const [draft, setDraft] = useState('');
  const [action, setAction] = useState<Action | null>(null);
  const [input, setInput] = useState('');
  const [reload, setReload] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const readBusy = useRef(false);
  const cursor = useRef<number | null>(null);
  const oldest = useRef<number | undefined>(undefined);
  const writeBusy = useRef(false);

  function merge(changes: Row[], existingOnly = false) {
    setRows(previous => {
      const map = new Map(previous.map(row => [row.message.id, row]));
      for (const change of changes) {
        const prior = map.get(change.message.id);
        if ((!existingOnly || prior) && (!prior || change.message_state_revision >= prior.message_state_revision))
          map.set(change.message.id, change);
      }
      return [...map.values()].sort((a, b) => a.message.id - b.message.id);
    });
  }

  function deny() {
    controller.current?.abort();
    cursor.current = null;
    setRows([]); setMore(false); setReady(false); setCanPublish(false);
    setAction(null); setInput(''); setDraft(''); setFeedback('');
  }

  async function read(kind: 'initial' | 'older' | 'poll', signal: AbortSignal) {
    if (signal.aborted || readBusy.current) return;
    readBusy.current = true;
    setReading(true);
    try {
      if (kind === 'poll') {
        if (cursor.current === null) return;
        let pending: boolean;
        do {
          const page = await channelApi.updates(sid, cid, cursor.current, signal);
          if (signal.aborted) return;
          setCanPublish(page.can_publish);
          for (const event of page.items) merge([event], event.event_type !== 'CREATED');
          cursor.current = page.next_cursor;
          pending = page.has_more;
        } while (pending && !signal.aborted);
      } else {
        const page = await channelApi.history(sid, cid, signal, kind === 'older' ? oldest.current : undefined);
        if (signal.aborted) return;
        merge(page.items.map(message => ({ message, message_state_revision: page.updates_revision })));
        oldest.current = page.items[0]?.id ?? oldest.current;
        setMore(page.has_more); setCanPublish(page.can_publish); setReady(true);
        if (kind === 'initial') cursor.current = page.updates_revision;
      }
      setReadError('');
    } catch (cause) {
      if (signal.aborted) return;
      if (cause instanceof ApiError && [401, 403, 404].includes(cause.status ?? 0)) deny();
      setReadError(errorText(cause));
    } finally {
      if (controller.current?.signal === signal) { readBusy.current = false; setReading(false); }
    }
  }

  useEffect(() => {
    const current = new AbortController();
    controller.current = current;
    readBusy.current = false;
    void read('initial', current.signal);
    const poll = () => {
      if (!document.hidden && navigator.onLine && cursor.current !== null) void read('poll', current.signal);
    };
    const timer = window.setInterval(poll, MESSAGE_POLL_INTERVAL_MS);
    window.addEventListener('online', poll);
    document.addEventListener('visibilitychange', poll);
    return () => {
      current.abort();
      window.clearInterval(timer);
      window.removeEventListener('online', poll);
      document.removeEventListener('visibilitychange', poll);
    };
  }, [sid, cid, reload]);

  async function save(kind: 'send' | 'policy' | 'action') {
    const signal = controller.current?.signal;
    if (!signal || signal.aborted || writeBusy.current || !ready) return;
    writeBusy.current = true;
    setBusy(true); setError(''); setFeedback('');
    try {
      if (kind === 'policy') {
        const updated = await channelApi.policy(sid, cid, !channel.is_read_only);
        if (!signal.aborted) { onPolicy(updated); setFeedback('Configuração do canal salva.'); }
      } else if (kind === 'send') {
        const result = await channelApi.send(sid, cid, draft.trim());
        if (!signal.aborted) { merge([result]); setDraft(''); setFeedback('Mensagem enviada.'); }
      } else if (action) {
        const id = action.message.id;
        if (action.kind === 'report') {
          await channelApi.report(sid, cid, id, input.trim());
          if (!signal.aborted) setFeedback('Denúncia registrada para triagem.');
        } else {
          const result = action.kind === 'edit' ? await channelApi.edit(sid, cid, id, input.trim())
            : await channelApi.remove(sid, cid, id);
          if (!signal.aborted) {
            merge([result]); setFeedback(action.kind === 'edit' ? 'Mensagem editada.' : 'Mensagem excluída.');
          }
        }
        if (!signal.aborted) setAction(null);
      }
    } catch (cause) {
      if (!signal.aborted) {
        if (cause instanceof ApiError && [401, 403, 404].includes(cause.status ?? 0)) deny();
        setError(errorText(cause));
      }
    } finally {
      // A read can invalidate access and start a new controller while this write finishes.
      writeBusy.current = false;
      setBusy(false);
    }
  }
  const editable = (m: MessageResponse) => canPublish && !m.is_deleted_for_everyone &&
    Date.now() <= Date.parse(m.created_at) + 900_000;
  function begin(kind: Action['kind'], message: MessageResponse) {
    setAction({ kind, message }); setInput(kind === 'edit' ? message.content : ''); setFeedback(''); setError('');
  }
  const selected = rows.find(r => r.message.id === action?.message.id)?.message;
  return <section className="channel-chat" aria-label={channel.name}><h4>{channel.name}</h4>
    {ready && owner && <button className="server-secondary-button" disabled={busy} onClick={() => void save('policy')}>{channel.is_read_only ? 'Liberar publicação' : 'Tornar somente leitura'}</button>}
    {reading && !ready && <p role="status">Carregando mensagens…</p>}
    {readError && <p role="alert">{readError}</p>}
    {error && <p role="alert">{error}</p>}
    {!ready && !reading && <button className="server-secondary-button" onClick={() => { setError(''); setReload(n => n + 1); }}>Recarregar histórico</button>}
    {feedback && <p role="status">{feedback}</p>}
    {ready && <>
      {more && <button className="server-secondary-button" disabled={reading} onClick={() => controller.current && void read('older', controller.current.signal)}>Mensagens anteriores</button>}
      {!rows.length && <p>Nenhuma mensagem neste canal.</p>}
      {rows.map(({ message: m }) => <article key={m.id}>
        <strong>{m.sender_id === userId ? 'Você' : 'Membro #' + m.sender_id}</strong> <time dateTime={m.created_at}>{new Date(m.created_at).toLocaleString('pt-BR')}</time>
        <p>{m.content}{m.edited_at && !m.is_deleted_for_everyone && <small> · editada</small>}</p>
        {!m.is_deleted_for_everyone && (m.sender_id === userId ? <>
          {editable(m) && <button className="server-secondary-button" disabled={busy} onClick={() => begin('edit', m)}>Editar mensagem</button>}
          <button className="server-secondary-button" disabled={busy} onClick={() => begin('remove', m)}>Excluir mensagem</button>
        </> : <button className="server-secondary-button" disabled={busy} onClick={() => begin('report', m)}>Denunciar mensagem</button>)}
      </article>)}
      {action && selected && !selected.is_deleted_for_everyone && (action.kind !== 'edit' || editable(selected)) &&
        <form onSubmit={e => { e.preventDefault(); void save('action'); }}>
          {action.kind === 'remove' ? <p>Excluir esta mensagem para todos?</p> : <label className="server-field">{action.kind === 'edit' ? 'Editar conteúdo' : 'Motivo da denúncia'}
            <textarea required disabled={busy} maxLength={action.kind === 'edit' ? 5000 : 500} value={input} onChange={e => setInput(e.target.value)} /></label>}
          <button className="server-secondary-button" disabled={busy || (action.kind !== 'remove' && !input.trim())}>Confirmar</button>
          <button className="server-secondary-button" type="button" disabled={busy} onClick={() => setAction(null)}>Cancelar</button>
        </form>}
      {canPublish ? <form onSubmit={e => { e.preventDefault(); void save('send'); }}>
        <label className="server-field">Mensagem no canal<textarea required disabled={busy} maxLength={5000} value={draft} onChange={e => setDraft(e.target.value)} /></label>
        <button className="server-primary-button" disabled={busy || !draft.trim()}>Enviar mensagem</button>
      </form> : <p>Você pode apenas ler as mensagens deste canal.</p>}
    </>}
  </section>;
}
