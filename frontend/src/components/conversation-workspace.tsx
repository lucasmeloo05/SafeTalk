import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  AlertCircle,
  Check,
  ChevronDown,
  LoaderCircle,
  MessageCircle,
  MessagesSquare,
  MoreHorizontal,
  Plus,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';
import { ApiError } from '@/lib/api';
import { useAuth } from '@/context/auth-context';
import {
  createDirectConversation,
  listConversations,
  listMessages,
  reportMessage,
  sendMessage,
  type ConversationResponse,
  type MessageResponse,
} from '@/services/conversation-api';

const PAGE_SIZE = 50;
export const MESSAGE_POLL_INTERVAL_MS = 3000;
type MessagePosition = Pick<MessageResponse, 'created_at' | 'id'>;

function compareMessagePositions(left: MessagePosition, right: MessagePosition) {
  const timeOrder = new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
  return timeOrder || left.id - right.id;
}

function sortConversationsByActivity(items: ConversationResponse[]) {
  return [...items].sort((left, right) => {
    const timeOrder = new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
    return timeOrder || right.id - left.id;
  });
}

function describeConversation(conversation: ConversationResponse, userId: number) {
  if (conversation.type === 'DIRECT') {
    const otherId = conversation.user_a_id === userId
      ? conversation.user_b_id
      : conversation.user_a_id;
    return otherId === null ? `Conversa #${conversation.id}` : `Usuário #${otherId}`;
  }
  return conversation.name || `Conversa #${conversation.id}`;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Horário indisponível';
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function mergeMessages(current: MessageResponse[], incoming: MessageResponse[]) {
  const byId = new Map<number, MessageResponse>();
  for (const message of [...current, ...incoming]) byId.set(message.id, message);
  return [...byId.values()].sort((left, right) => {
    const timeOrder = new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
    return timeOrder || left.id - right.id;
  });
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

type ConversationWorkspaceProps = {
  createDialogOpen: boolean;
  onCreateDialogOpenChange: (open: boolean) => void;
};

export function ConversationWorkspace({ createDialogOpen, onCreateDialogOpenChange }: ConversationWorkspaceProps) {
  const { user } = useAuth();
  const [conversations, setConversations] = useState<ConversationResponse[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selectedIdRef = useRef<number | null>(null);
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [accessLostForId, setAccessLostForId] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [messagesLoadedForId, setMessagesLoadedForId] = useState<number | null>(null);
  const [pollingAvailable, setPollingAvailable] = useState(
    () => typeof document === 'undefined' || (!document.hidden && navigator.onLine),
  );
  const oldestMessageRef = useRef<MessagePosition | null>(null);
  const newestMessageRef = useRef<MessagePosition | null>(null);
  const accessLostRef = useRef<number | null>(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [openMessageMenu, setOpenMessageMenu] = useState<number | null>(null);
  const [reportTarget, setReportTarget] = useState<MessageResponse | null>(null);
  const [reportReason, setReportReason] = useState('');
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportSending, setReportSending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [recipientId, setRecipientId] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [messageRequestAttempt, setMessageRequestAttempt] = useState(0);

  const selectedConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === selectedId) ?? null,
    [conversations, selectedId],
  );

  const refreshConversations = useCallback(async () => {
    setConversationsLoading(true);
    setConversationsError(null);
    try {
      const result = await listConversations();
      setConversations(result);
    } catch (error) {
      setConversationsError(getErrorMessage(error, 'Não foi possível carregar suas conversas.'));
    } finally {
      setConversationsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    if (createDialogOpen) setCreateError(null);
  }, [createDialogOpen]);

  useEffect(() => {
    if (conversations.length === 0) {
      selectedIdRef.current = null;
      setSelectedId(null);
      return;
    }
    if (selectedId === null || !conversations.some((conversation) => conversation.id === selectedId)) {
      selectedIdRef.current = conversations[0].id;
      setSelectedId(conversations[0].id);
    }
  }, [conversations, selectedId]);

  useEffect(() => {
    const updateAvailability = () => {
      setPollingAvailable(!document.hidden && navigator.onLine);
    };
    document.addEventListener('visibilitychange', updateAvailability);
    window.addEventListener('online', updateAvailability);
    window.addEventListener('offline', updateAvailability);
    updateAvailability();
    return () => {
      document.removeEventListener('visibilitychange', updateAvailability);
      window.removeEventListener('online', updateAvailability);
      window.removeEventListener('offline', updateAvailability);
    };
  }, []);

  useEffect(() => {
    if (accessLostRef.current !== selectedId) {
      accessLostRef.current = null;
      setAccessLostForId(null);
    }
    selectedIdRef.current = selectedId;
    if (selectedId === null) {
      setMessages([]);
      setMessagesError(null);
      setHasMore(false);
      setMessagesLoadedForId(null);
      oldestMessageRef.current = null;
      newestMessageRef.current = null;
      return;
    }

    let active = true;
    setMessages([]);
    setMessagesLoading(true);
    setMessagesError(null);
    setPollError(null);
    setSendError(null);
    setDraft('');
    setHasMore(false);
    setMessagesLoadedForId(null);
    oldestMessageRef.current = null;
    newestMessageRef.current = null;

    // The explicit latest flag requests the newest chronological window while
    // preserving the original offset behavior for existing API clients.
    listMessages(selectedId, PAGE_SIZE, undefined, { latest: true })
      .then((page) => {
        if (!active || selectedIdRef.current !== selectedId) return;
        setMessages(mergeMessages([], page));
        oldestMessageRef.current = page[0] ?? null;
        newestMessageRef.current = page.at(-1)
          ? { created_at: page.at(-1)!.created_at, id: page.at(-1)!.id }
          : selectedConversation
            ? { created_at: selectedConversation.created_at, id: 0 }
            : null;
        setHasMore(page.length === PAGE_SIZE);
        setMessagesLoadedForId(selectedId);
      })
      .catch((error: unknown) => {
        if (active && selectedIdRef.current === selectedId) {
          setMessagesError(getErrorMessage(error, 'Não foi possível carregar as mensagens.'));
        }
      })
      .finally(() => {
        if (active && selectedIdRef.current === selectedId) setMessagesLoading(false);
      });

    return () => { active = false; };
  }, [selectedId, messageRequestAttempt, selectedConversation?.created_at]);

  useEffect(() => {
    if (
      selectedId === null
      || user === null
      || messagesLoadedForId !== selectedId
      || !pollingAvailable
      || accessLostForId === selectedId
    ) return;

    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const scheduleNext = () => {
      if (active) timer = setTimeout(() => { void poll(); }, MESSAGE_POLL_INTERVAL_MS);
    };
    const poll = async () => {
      if (!active || selectedIdRef.current !== selectedId || controller) return;
      const cursor = newestMessageRef.current;
      if (!cursor) {
        scheduleNext();
        return;
      }
      controller = new AbortController();
      const requestController = controller;
      try {
        const incoming = await listMessages(
          selectedId,
          PAGE_SIZE,
          undefined,
          {
            cursor: { direction: 'after', created_at: cursor.created_at, id: cursor.id },
            signal: requestController.signal,
          },
        );
        if (!active || selectedIdRef.current !== selectedId) return;
        setPollError(null);
        if (incoming.length > 0) {
          setMessages((current) => mergeMessages(current, incoming));
          const latest = incoming.at(-1)!;
          if (!newestMessageRef.current || compareMessagePositions(latest, newestMessageRef.current) > 0) {
            newestMessageRef.current = { created_at: latest.created_at, id: latest.id };
          }
          setConversations((current) => sortConversationsByActivity(current.map((conversation) => (
            conversation.id === selectedId && new Date(latest.created_at).getTime() > new Date(conversation.updated_at).getTime()
              ? { ...conversation, updated_at: latest.created_at }
              : conversation
          ))));
        }
      } catch (error) {
        if (active && selectedIdRef.current === selectedId && !requestController.signal.aborted) {
          if (error instanceof ApiError && error.status === 403) {
            active = false;
            accessLostRef.current = selectedId;
            setAccessLostForId(selectedId);
            setMessages([]);
            setMessagesError(null);
            setPollError(null);
            setMessagesLoading(false);
            setSendError(null);
            setDraft('');
            setHasMore(false);
            setLoadingMore(false);
            setSending(false);
            setOpenMessageMenu(null);
            setReportTarget(null);
            setReportReason('');
            setReportError(null);
            setReportSending(false);
            setNotice(null);
            setMessagesLoadedForId(null);
            oldestMessageRef.current = null;
            newestMessageRef.current = null;
            return;
          }
          setPollError(getErrorMessage(error, 'Atualização automática indisponível. Tentaremos novamente.'));
        }
      } finally {
        if (controller === requestController) controller = undefined;
        scheduleNext();
      }
    };

    scheduleNext();
    return () => {
      active = false;
      if (timer !== undefined) clearTimeout(timer);
      controller?.abort();
    };
  }, [selectedId, user?.id, messagesLoadedForId, pollingAvailable, accessLostForId]);

  async function handleLoadMore() {
    if (
      selectedId === null
      || accessLostRef.current === selectedId
      || loadingMore
      || !hasMore
      || !oldestMessageRef.current
    ) return;
    const conversationId = selectedId;
    const cursor = oldestMessageRef.current;
    setLoadingMore(true);
    setMessagesError(null);
    try {
      const page = await listMessages(conversationId, PAGE_SIZE, undefined, {
        cursor: {
          direction: 'before',
          created_at: cursor.created_at,
          id: cursor.id,
        },
      });
      if (selectedIdRef.current !== conversationId || accessLostRef.current === conversationId) return;
      setMessages((current) => mergeMessages(current, page));
      if (page.length > 0) oldestMessageRef.current = { created_at: page[0].created_at, id: page[0].id };
      setHasMore(page.length === PAGE_SIZE);
    } catch (error) {
      if (selectedIdRef.current === conversationId && accessLostRef.current !== conversationId) {
        setMessagesError(getErrorMessage(error, 'Não foi possível carregar mais mensagens.'));
      }
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedId === null || accessLostRef.current === selectedId) return;
    const conversationId = selectedId;
    const content = draft.trim();
    if (!content || content.length > 5000 || sending) return;

    setSending(true);
    setSendError(null);
    setNotice(null);
    try {
      const created = await sendMessage(conversationId, content);
      if (selectedIdRef.current !== conversationId || accessLostRef.current === conversationId) return;
      setMessages((current) => mergeMessages(current, [created]));
      // The POST confirms only this message, not every message after the
      // polling cursor. Leave the cursor for the next server read to advance.
      setDraft('');
      setConversations((current) => sortConversationsByActivity(current
        .map((conversation) => conversation.id === conversationId
          ? { ...conversation, updated_at: created.created_at }
          : conversation)));
    } catch (error) {
      if (selectedIdRef.current === conversationId && accessLostRef.current !== conversationId) {
        setSendError(getErrorMessage(error, 'Não foi possível enviar a mensagem.'));
      }
    } finally {
      setSending(false);
    }
  }

  async function handleReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reportTarget || (selectedId !== null && accessLostRef.current === selectedId)) return;
    const conversationId = selectedId;
    const reason = reportReason.trim();
    if (!reason || reason.length > 500 || reportSending) return;

    setReportSending(true);
    setReportError(null);
    try {
      await reportMessage(reportTarget.id, reason);
      if (selectedId !== null && accessLostRef.current === selectedId) return;
      setReportTarget(null);
      setReportReason('');
      setNotice('Denúncia enviada. Obrigado por ajudar a manter o SafeTalk seguro.');
    } catch (error) {
      if (conversationId === null || accessLostRef.current !== conversationId) {
        setReportError(getErrorMessage(error, 'Não foi possível enviar a denúncia.'));
      }
    } finally {
      setReportSending(false);
    }
  }

  async function handleCreateConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = Number(recipientId);
    if (!Number.isSafeInteger(id) || id < 1 || creating) {
      setCreateError('Informe um ID de usuário válido.');
      return;
    }

    setCreating(true);
    setCreateError(null);
    try {
      const conversation = await createDirectConversation(id);
      setConversations((current) => [
        conversation,
        ...current.filter((item) => item.id !== conversation.id),
      ].sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()));
      selectedIdRef.current = conversation.id;
      setSelectedId(conversation.id);
      onCreateDialogOpenChange(false);
      setRecipientId('');
      setNotice(null);
    } catch (error) {
      setCreateError(getErrorMessage(error, 'Não foi possível iniciar a conversa.'));
    } finally {
      setCreating(false);
    }
  }

  if (!user) return null;

  return (
    <>
      <div className="chat-workspace">
        <section className="chat-list-panel" aria-label="Lista de conversas">
          <header className="chat-list-panel__header">
            <div>
              <h2>Suas conversas</h2>
              <p>{conversationsLoading ? 'Carregando…' : `${conversations.length} ${conversations.length === 1 ? 'conversa' : 'conversas'}`}</p>
            </div>
            <button
              className="chat-list-panel__add"
              type="button"
              onClick={() => { onCreateDialogOpenChange(true); setCreateError(null); }}
              aria-label="Iniciar conversa"
              title="Iniciar conversa pelo ID do usuário"
            >
              <Plus size={17} />
            </button>
          </header>

          {conversationsError ? (
            <div className="chat-list-state chat-list-state--error" role="alert">
              <AlertCircle size={19} />
              <p>{conversationsError}</p>
              <button type="button" onClick={() => void refreshConversations()}>Tentar novamente</button>
            </div>
          ) : conversationsLoading ? (
            <div className="chat-list-state" role="status"><LoaderCircle className="spin" size={19} /><span>Carregando conversas…</span></div>
          ) : conversations.length === 0 ? (
            <div className="chat-list-state chat-list-state--empty">
              <MessageCircle size={21} />
              <strong>Ainda sem conversas</strong>
              <p>Você pode iniciar uma usando o ID de outra pessoa.</p>
            </div>
          ) : (
            <div className="chat-list-panel__items">
              {conversations.map((conversation) => {
                const title = describeConversation(conversation, user.id);
                return (
                  <button
                    key={conversation.id}
                    className={`conversation-list-item${selectedId === conversation.id ? ' is-selected' : ''}`}
                    type="button"
                    onClick={() => { selectedIdRef.current = conversation.id; setSelectedId(conversation.id); }}
                    aria-label={`Abrir conversa com ${title}`}
                    aria-current={selectedId === conversation.id ? 'page' : undefined}
                  >
                    <span className="conversation-list-item__avatar"><MessageCircle size={17} /></span>
                    <span className="conversation-list-item__details">
                      <strong>{title}</strong>
                      <span>Atualizada {formatDate(conversation.updated_at)}</span>
                    </span>
                    <ChevronDown className="conversation-list-item__chevron" size={15} />
                  </button>
                );
              })}
            </div>
          )}
          <footer className="chat-list-panel__footer"><ShieldCheck size={14} /> Conversas privadas</footer>
        </section>

        <section className="chat-thread-panel" aria-label="Mensagens da conversa">
          {selectedConversation ? (
            <>
              <header className="chat-thread__header">
                <span className="chat-thread__avatar"><MessageCircle size={17} /></span>
                <div className="chat-thread__identity">
                  <strong>{describeConversation(selectedConversation, user.id)}</strong>
                  <span>{selectedConversation.type === 'DIRECT' ? 'Conversa direta' : 'Conversa'} · atualização {formatDate(selectedConversation.updated_at)}</span>
                </div>
                {selectedConversation.type === 'DIRECT' && <span className="chat-thread__privacy"><ShieldCheck size={14} /> Privada</span>}
              </header>

              {notice && <div className="chat-notice" role="status"><Check size={15} />{notice}<button type="button" onClick={() => setNotice(null)} aria-label="Fechar aviso"><X size={14} /></button></div>}

              {pollError && <div className="chat-poll-warning" role="status">Atualização automática pausada temporariamente: {pollError}</div>}

              <div className="chat-messages" aria-live="polite">
                {hasMore && !messagesLoading && (
                  <button className="chat-load-more" type="button" onClick={() => void handleLoadMore()} disabled={loadingMore}>
                    {loadingMore ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}
                    {loadingMore ? 'Carregando…' : 'Carregar mais mensagens'}
                  </button>
                )}
                {accessLostForId === selectedId ? (
                  <div className="chat-message-state chat-message-state--error" role="alert">
                    <AlertCircle size={20} />
                    <p>Você perdeu o acesso a esta conversa. As mensagens carregadas foram removidas desta tela.</p>
                  </div>
                ) : messagesLoading ? (
                  <div className="chat-message-state" role="status"><LoaderCircle className="spin" size={20} /><span>Carregando mensagens…</span></div>
                ) : messagesError ? (
                  <div className="chat-message-state chat-message-state--error" role="alert"><AlertCircle size={20} /><p>{messagesError}</p><button type="button" onClick={() => setMessageRequestAttempt((attempt) => attempt + 1)}>Tentar novamente</button></div>
                ) : messages.length === 0 ? (
                  <div className="chat-message-state chat-message-state--empty">
                    <span className="chat-message-state__icon"><MessagesSquare size={22} /></span>
                    <strong>Esta conversa ainda não tem mensagens</strong>
                    <p>Envie a primeira mensagem para começar.</p>
                  </div>
                ) : (
                  <div className="chat-message-list">
                    {messages.map((message) => {
                      const ownMessage = message.sender_id === user.id;
                      return (
                        <article key={message.id} className={`chat-message-row${ownMessage ? ' is-own' : ''}`}>
                          {!ownMessage && <span className="chat-message-row__avatar" aria-hidden="true">{describeConversation(selectedConversation, user.id).slice(0, 1)}</span>}
                          <div className="chat-message-row__body">
                            <div className="chat-message-row__meta">
                              <span>{ownMessage ? 'Você' : describeConversation(selectedConversation, user.id)}</span>
                              <time dateTime={message.created_at}>{formatDate(message.created_at)}</time>
                            </div>
                            <div className="chat-message-row__content-wrap">
                              {message.is_deleted_for_everyone && <span className="chat-message-deleted-label">Apagada para todos</span>}
                              <p className={`chat-message-bubble${ownMessage ? ' is-own' : ''}`}>{message.content}</p>
                              {!ownMessage && (
                                <div className="chat-message-menu-wrap">
                                  <button
                                    className="chat-message-menu-trigger"
                                    type="button"
                                    aria-label={`Opções da mensagem ${message.id}`}
                                    aria-expanded={openMessageMenu === message.id}
                                    onClick={() => setOpenMessageMenu((current) => current === message.id ? null : message.id)}
                                  ><MoreHorizontal size={17} /></button>
                                  {openMessageMenu === message.id && (
                                    <div className="chat-message-menu" role="menu">
                                      <button type="button" role="menuitem" onClick={() => { setReportTarget(message); setReportReason(''); setReportError(null); setOpenMessageMenu(null); }}>
                                        <ShieldCheck size={14} /> Denunciar mensagem
                                      </button>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                )}
              </div>

              {sendError && <p className="chat-send-error" role="alert"><AlertCircle size={14} />{sendError}</p>}
              <form className="chat-composer" onSubmit={handleSend}>
                <textarea
                  aria-label="Mensagem"
                  placeholder="Escreva sua mensagem…"
                  value={draft}
                  maxLength={5000}
                  rows={2}
                  onChange={(event) => setDraft(event.target.value)}
                  disabled={accessLostForId === selectedId || messagesLoading || Boolean(messagesError) || sending}
                />
                <div className="chat-composer__footer">
                  <span>{draft.length.toLocaleString('pt-BR')} / 5.000</span>
                  <button type="submit" disabled={accessLostForId === selectedId || !draft.trim() || draft.length > 5000 || sending || messagesLoading || Boolean(messagesError)} aria-label="Enviar mensagem">
                    {sending ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />}
                    <span>{sending ? 'Enviando…' : 'Enviar'}</span>
                  </button>
                </div>
              </form>
            </>
          ) : (
            <div className="chat-thread-empty">
              <span className="chat-thread-empty__icon"><MessagesSquare size={24} /></span>
              <h2>{conversationsLoading ? 'Carregando seu espaço' : 'Seu espaço de conversas'}</h2>
              <p>{conversationsLoading ? 'Buscando suas conversas…' : 'Selecione uma conversa para ver as mensagens ou inicie uma pelo ID de outra pessoa.'}</p>
              {!conversationsLoading && conversations.length === 0 && (
                <button type="button" onClick={() => { onCreateDialogOpenChange(true); setCreateError(null); }}><Plus size={15} /> Iniciar conversa</button>
              )}
            </div>
          )}
        </section>
      </div>

      {createDialogOpen && (
        <div className="chat-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCreateDialogOpenChange(false); }}>
          <section className="chat-modal" role="dialog" aria-modal="true" aria-labelledby="create-conversation-title">
            <header className="chat-modal__header"><div><span className="chat-modal__icon"><Plus size={17} /></span><div><h2 id="create-conversation-title">Iniciar conversa</h2><p>Informe o ID de usuário da pessoa.</p></div></div><button type="button" onClick={() => onCreateDialogOpenChange(false)} aria-label="Fechar"><X size={17} /></button></header>
            <form onSubmit={handleCreateConversation}>
              <label htmlFor="recipient-id">ID do usuário</label>
              <input id="recipient-id" type="number" min="1" step="1" value={recipientId} onChange={(event) => setRecipientId(event.target.value)} required />
              <p className="chat-modal__hint">Não há busca de usuários nesta versão. As regras de amizade, bloqueio e privacidade serão verificadas pela API.</p>
              {createError && <p className="chat-modal__error" role="alert">{createError}</p>}
              <footer><button className="chat-modal__cancel" type="button" onClick={() => onCreateDialogOpenChange(false)}>Cancelar</button><button className="chat-modal__submit" type="submit" disabled={creating || !recipientId}>{creating ? 'Iniciando…' : 'Continuar'}</button></footer>
            </form>
          </section>
        </div>
      )}

      {reportTarget && (
        <div className="chat-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setReportTarget(null); }}>
          <section className="chat-modal" role="dialog" aria-modal="true" aria-labelledby="report-message-title">
            <header className="chat-modal__header"><div><span className="chat-modal__icon chat-modal__icon--report"><ShieldCheck size={17} /></span><div><h2 id="report-message-title">Denunciar mensagem</h2><p>A denúncia será encaminhada para análise.</p></div></div><button type="button" onClick={() => setReportTarget(null)} aria-label="Fechar"><X size={17} /></button></header>
            <form onSubmit={handleReport}>
              <label htmlFor="report-reason">Motivo</label>
              <textarea id="report-reason" value={reportReason} maxLength={500} rows={4} placeholder="Conte por que esta mensagem deve ser analisada…" onChange={(event) => setReportReason(event.target.value)} required />
              <div className="chat-modal__counter">{reportReason.length} / 500</div>
              {reportError && <p className="chat-modal__error" role="alert">{reportError}</p>}
              <footer><button className="chat-modal__cancel" type="button" onClick={() => setReportTarget(null)}>Cancelar</button><button className="chat-modal__submit" type="submit" disabled={reportSending || !reportReason.trim()}>{reportSending ? 'Enviando…' : 'Enviar denúncia'}</button></footer>
            </form>
          </section>
        </div>
      )}
    </>
  );
}
