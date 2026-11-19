import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Check, ChevronLeft, ChevronRight, LoaderCircle, MessageCircle, Search, ShieldCheck, UserMinus, UserPlus, Users, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '@/lib/api';
import { DashboardLayout } from '@/components/dashboard-layout';
import { createDirectConversation } from '@/services/conversation-api';
import {
  acceptFriendRequest, cancelFriendRequest, getPrivacySettings, listSocial, SOCIAL_PAGE_SIZE,
  rejectFriendRequest, removeFriend, searchUsers, sendFriendRequest,
  updatePrivacySettings, type SocialActionResponse, type PrivacySettings, type SocialListItem, type UserDiscovery,
} from '@/services/social-api';

import { BlockButton, BlockedUsers } from '@/components/user-blocks';

type Tab = 'friends' | 'received' | 'sent' | 'privacy';
type ListKind = Exclude<Tab, 'privacy'>;
const errorText = (error: unknown) => error instanceof ApiError ? error.message : 'Não foi possível concluir a solicitação.';

function useRelationPage(path: Parameters<typeof listSocial>[0]) {
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState({ items: [] as SocialListItem[], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    listSocial(path, SOCIAL_PAGE_SIZE, offset).then(next => {
      if (!active) return;
      if (!next.items.length && offset > 0 && offset >= next.total) {
        setOffset(Math.floor(Math.max(0, next.total - 1) / SOCIAL_PAGE_SIZE) * SOCIAL_PAGE_SIZE);
        return;
      }
      setPage(next);
    }).catch(cause => { if (active) setError(errorText(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [path, offset, revision]);
  return { ...page, offset, setOffset, loading, error, refresh: () => setRevision(value => value + 1) };
}

export function SocialPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('friends');
  const friends = useRelationPage('friends');
  const received = useRelationPage('requests/received');
  const sent = useRelationPage('requests/sent');
  const [privacy, setPrivacy] = useState<PrivacySettings | null>(null);
  const [query, setQuery] = useState('');
  const queryRef = useRef('');
  const searchRequestId = useRef(0);
  const searchUpdates = useRef(new Map<number, Partial<UserDiscovery>>());
  const [submittedSearch, setSubmittedSearch] = useState<string | null>(null);
  const [searchOffset, setSearchOffset] = useState(0);
  const [searchTotal, setSearchTotal] = useState(0);
  const [results, setResults] = useState<UserDiscovery[]>([]);
  const [searchError, setSearchError] = useState('');
  const [error, setError] = useState('');
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getPrivacySettings().then(settings => { if (active) setPrivacy(settings); })
      .catch(cause => { if (active) setError(errorText(cause)); });
    return () => { active = false; searchRequestId.current += 1; };
  }, []);

  async function loadSearchPage(term: string, offset: number) {
    const requestId = ++searchRequestId.current;
    searchUpdates.current.clear();
    setSubmittedSearch(term);
    setSearchOffset(offset);
    setSearching(true);
    setSearchError('');
    setResults([]);
    try {
      const page = await searchUsers(term, SOCIAL_PAGE_SIZE, offset);
      if (requestId !== searchRequestId.current || queryRef.current.trim() !== term) return;
      setResults(page.items.map(item => ({ ...item, ...searchUpdates.current.get(item.id) })));
      setSearchTotal(page.total);
    } catch (cause) {
      if (requestId === searchRequestId.current && queryRef.current.trim() === term) setSearchError(errorText(cause));
    } finally {
      if (requestId === searchRequestId.current) setSearching(false);
    }
  }

  function handleQueryChange(value: string) {
    queryRef.current = value;
    searchRequestId.current += 1;
    setQuery(value);
    setSubmittedSearch(null);
    setSearchOffset(0);
    setSearchTotal(0);
    setResults([]);
    setSearchError('');
    setSearching(false);
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    const term = query.trim();
    if (term.length < 2 || term.length > 30 || searching) return;
    await loadSearchPage(term, 0);
  }

  async function runAction(key: string, action: () => Promise<SocialActionResponse>) {
    setBusy(key); setError('');
    try {
      const relation = await action();
      const status = relation.status;
      const update: Partial<UserDiscovery> = {
        relationship_status: status === 'ACCEPTED' ? 'FRIENDS' : status === 'PENDING' ? 'REQUEST_SENT' : 'NONE',
        friendship_id: status === 'ACCEPTED' || status === 'PENDING' ? relation.friendship_id : null,
      };
      searchUpdates.current.set(relation.user_id, update);
      setResults(items => items.map(item => item.id === relation.user_id ? { ...item, ...update } : item));
      if (status === 'ACCEPTED' || status === 'REMOVED') friends.refresh();
      if (status === 'ACCEPTED' || status === 'REJECTED') received.refresh();
      if (status === 'PENDING' || status === 'CANCELLED') sent.refresh();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(null); }
  }

  const [blockRevision, setBlockRevision] = useState(0);
  function afterBlock() {
    handleQueryChange('');
    friends.refresh();
    sent.refresh();
    received.refresh();
    setBlockRevision(value => value + 1);
  }

  async function openConversation(userId: number) {
    setBusy(`chat-${userId}`); setError('');
    try {
      const conversation = await createDirectConversation(userId);
      navigate('/app', { state: { openConversationId: conversation.id } });
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(null); }
  }

  async function changePrivacy(key: keyof PrivacySettings, value: boolean) {
    if (!privacy) return;
    const previous = privacy;
    setPrivacy({ ...privacy, [key]: value });
    setBusy(`privacy-${key}`); setError('');
    try { setPrivacy(await updatePrivacySettings({ [key]: value })); }
    catch (cause) { setPrivacy(previous); setError(errorText(cause)); }
    finally { setBusy(null); }
  }

  function pagination(kind: string, total: number, offset: number, onChange: (next: number) => void, disabled: boolean) {
    const pageCount = Math.max(1, Math.ceil(total / SOCIAL_PAGE_SIZE));
    const page = Math.floor(offset / SOCIAL_PAGE_SIZE) + 1;
    return <nav className="social-pagination" aria-label={kind}>
      <button className="social-icon-button" aria-label={`Página anterior ${kind.toLowerCase()}`} disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - SOCIAL_PAGE_SIZE))}><ChevronLeft size={16} /></button>
      <span>{offset > 0 && offset >= total ? 'Página sem resultados' : total === 0 ? '0 resultados' : `Página ${page} de ${pageCount} · ${total} resultados`}</span>
      <button className="social-icon-button" aria-label={`Próxima página ${kind.toLowerCase()}`} disabled={disabled || offset + SOCIAL_PAGE_SIZE >= total} onClick={() => onChange(offset + SOCIAL_PAGE_SIZE)}><ChevronRight size={16} /></button>
    </nav>;
  }

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'friends', label: 'Amigos', count: friends.total },
    { id: 'received', label: 'Recebidos', count: received.total },
    { id: 'sent', label: 'Enviados', count: sent.total },
    { id: 'privacy', label: 'Privacidade' },
  ];

  function relationshipRows(items: SocialListItem[], kind: ListKind) {
    if (!items.length) return <div className="social-empty"><Users size={22} /><strong>{kind === 'friends' ? 'Sua lista está começando' : 'Nada por aqui'}</strong><span>{kind === 'friends' ? 'Pesquise pessoas para adicionar aos seus amigos.' : 'Não há solicitações nesta seção.'}</span></div>;
    return <div className="social-people-list">{items.map((item) => <article className="social-person" key={item.friendship_id}>
      <span className="social-avatar">{item.username.slice(0, 1).toUpperCase()}</span>
      <div className="social-person__identity"><strong>{item.username}</strong><span>{kind === 'friends' ? 'Amigo' : kind === 'received' ? 'Solicitação recebida' : 'Aguardando resposta'}</span></div>
      <div className="social-person__actions">
        <BlockButton id={item.user_id} name={item.username} onBlocked={afterBlock} disabled={busy !== null}
          onBusyChange={pending => setBusy(pending ? 'block' : null)} />
        {kind === 'friends' ? <>
          <button className="social-button social-button--primary" disabled={busy !== null} onClick={() => void openConversation(item.user_id)}><MessageCircle size={15} /> Conversar</button>
          <button className="social-icon-button" aria-label={`Remover ${item.username} dos amigos`} disabled={busy !== null} onClick={() => void runAction(`remove-${item.user_id}`, () => removeFriend(item.user_id))}><UserMinus size={16} /></button>
        </> : kind === 'received' ? <>
          <button className="social-button social-button--primary" disabled={busy !== null} onClick={() => void runAction(`accept-${item.friendship_id}`, () => acceptFriendRequest(item.friendship_id))}><Check size={15} /> Aceitar</button>
          <button className="social-icon-button" aria-label={`Recusar ${item.username}`} disabled={busy !== null} onClick={() => void runAction(`reject-${item.friendship_id}`, () => rejectFriendRequest(item.friendship_id))}><X size={16} /></button>
        </> : <button className="social-button" disabled={busy !== null} onClick={() => void runAction(`cancel-${item.friendship_id}`, () => cancelFriendRequest(item.friendship_id))}>Cancelar</button>}
      </div>
    </article>)}</div>;
  }

  const selectedListKind: ListKind | null = tab === 'privacy' ? null : tab;
  const selectedList = tab === 'friends' ? friends : tab === 'received' ? received : sent;

  return <DashboardLayout title="Pessoas" description="Encontre pessoas e gerencie suas conexões com privacidade.">
    <section className="social-page">
      <div className="social-intro"><div><span className="dashboard-eyebrow"><ShieldCheck size={14} /> CONEXÕES COM CONTROLE</span><h2>Seu círculo, do seu jeito.</h2><p>Pesquise por username, envie solicitações e escolha quem pode iniciar uma conversa.</p></div><span className="social-intro__mark"><Users size={25} /></span></div>
      <form className="social-search" onSubmit={(event) => void handleSearch(event)}>
        <label htmlFor="people-search"><Search size={17} /><input id="people-search" aria-label="Buscar por username" value={query} onChange={(event) => handleQueryChange(event.target.value)} placeholder="Buscar por username" minLength={2} maxLength={30} /></label>
        <button className="social-button social-button--primary" type="submit" disabled={searching || query.trim().length < 2}>{searching ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />} Buscar</button>
      </form>
      {searchError && <p className="social-error" role="alert">{searchError}</p>}
      {searching && <div className="social-loading"><LoaderCircle className="spin" size={19} /> Buscando pessoas…</div>}
      {!searching && !searchError && (results.length > 0 || searchOffset > 0) && <section className="social-search-results" aria-label="Resultados da busca"><h3>Resultados para “{submittedSearch}”</h3><div className="social-people-list">{results.map((person) => <article className="social-person" key={person.id}>
        <span className="social-avatar">{person.username.slice(0, 1).toUpperCase()}</span><div className="social-person__identity"><strong>{person.username}</strong><span>{person.relationship_status === 'FRIENDS' ? 'Já são amigos' : person.relationship_status === 'REQUEST_SENT' ? 'Solicitação enviada' : person.relationship_status === 'REQUEST_RECEIVED' ? 'Esta pessoa enviou uma solicitação' : 'Pessoa encontrada'}</span></div>
        <BlockButton id={person.id} name={person.username} onBlocked={afterBlock} disabled={busy !== null}
          onBusyChange={pending => setBusy(pending ? 'block' : null)} />
        {person.relationship_status === 'NONE' ? <button className="social-button social-button--primary" disabled={busy !== null} onClick={() => void runAction('request', () => sendFriendRequest(person.id))}><UserPlus size={15} /> Adicionar</button> : person.relationship_status === 'REQUEST_RECEIVED' && person.friendship_id !== null ? <button className="social-button social-button--primary" disabled={busy !== null} onClick={() => void runAction('accept', () => acceptFriendRequest(person.friendship_id!))}><Check size={15} /> Aceitar</button> : person.relationship_status === 'FRIENDS' ? <button className="social-button" disabled={busy !== null} onClick={() => void openConversation(person.id)}><MessageCircle size={15} /> Conversar</button> : <span className="social-status">Solicitação enviada</span>}
      </article>)}</div>{!results.length && <p>Não há resultados nesta página.</p>}{pagination('resultados da busca', searchTotal, searchOffset, (next) => { if (submittedSearch) void loadSearchPage(submittedSearch, next); }, searching)}</section>}
      {submittedSearch && searchOffset === 0 && results.length === 0 && !searching && !searchError && <p className="social-search-empty">Nenhum usuário encontrado. A busca mostra apenas usernames de contas disponíveis.</p>}

      {tab === 'privacy' && <BlockedUsers key={blockRevision} onUnblocked={() => handleQueryChange('')} />}
      <section className="social-management">
        <nav className="social-tabs" aria-label="Gerenciar conexões">{tabs.map((item) => <button key={item.id} className={tab === item.id ? 'is-active' : ''} onClick={() => setTab(item.id)}>{item.label}{item.count !== undefined && <span>{item.count}</span>}</button>)}</nav>
        {error && <p className="social-error" role="alert">{error}</p>}
        {tab !== 'privacy' && selectedList.error && <p role="alert">{selectedList.error}</p>}
        {(tab === 'privacy' ? !privacy && !error : selectedList.loading) ? <div className="social-loading"><LoaderCircle className="spin" size={19} /> Carregando conexões…</div> : tab === 'privacy' ? privacy && <div className="social-privacy">
          <article><div><strong>Solicitações de amizade</strong><p>Permite que outras pessoas enviem pedidos para você.</p></div><button role="switch" aria-checked={privacy.allow_friend_requests} aria-label="Permitir solicitações de amizade" disabled={busy !== null} className={`social-switch${privacy.allow_friend_requests ? ' is-on' : ''}`} onClick={() => void changePrivacy('allow_friend_requests', !privacy.allow_friend_requests)}><span /></button></article>
          <article><div><strong>Mensagens de pessoas que não são amigas</strong><p>Quando desativado, apenas amigos podem iniciar conversas diretas com você.</p></div><button role="switch" aria-checked={privacy.allow_messages_from_strangers} aria-label="Permitir mensagens de pessoas que não são amigas" disabled={busy !== null} className={`social-switch${privacy.allow_messages_from_strangers ? ' is-on' : ''}`} onClick={() => void changePrivacy('allow_messages_from_strangers', !privacy.allow_messages_from_strangers)}><span /></button></article>
        </div> : <>{relationshipRows(selectedList.items, selectedListKind!)}{pagination(`lista de ${tab === 'friends' ? 'amigos' : tab === 'received' ? 'solicitações recebidas' : 'solicitações enviadas'}`, selectedList.total, selectedList.offset, selectedList.setOffset, selectedList.loading || busy !== null)}</>}
      </section>
      <p className="social-footnote"><ShieldCheck size={14} /> Bloqueios e regras de privacidade continuam sendo aplicados pelo servidor em todas as conversas.</p>
    </section>
  </DashboardLayout>;
}
