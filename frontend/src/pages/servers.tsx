import { useCallback, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, LoaderCircle, Plus, Server, ShieldCheck } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { DashboardLayout } from '@/components/dashboard-layout';
import { ApiError } from '@/lib/api';
import { useAuth } from '@/context/auth-context';
import { acceptServerInvite, createServer, listServers, type ServerResponse } from '@/services/server-api';

function errorMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 403) return error.message.startsWith('Servidores +18') ? error.message : 'A API não autorizou esta operação.';
  if (error.status === 404) return 'Servidor indisponível. Confira sua participação e a idade declarada para acesso +18.';
  if (error.status === 422) return error.message || 'Confira os dados informados.';
  return error.message;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium' }).format(new Date(value));
}

export function ServersPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [servers, setServers] = useState<ServerResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [name, setName] = useState('');
  const [adult, setAdult] = useState(false);
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [inviteServerId, setInviteServerId] = useState('');
  const [inviteToken, setInviteToken] = useState('');
  const [acceptingInvite, setAcceptingInvite] = useState(false);
  const [inviteError, setInviteError] = useState('');
  const [joinedServerId, setJoinedServerId] = useState<number | null>(null);
  const listRequest = useRef(0);
  const mounted = useRef(false);

  const loadServers = useCallback(async () => {
    const request = ++listRequest.current;
    setLoading(true);
    setLoadError('');
    try {
      const data = await listServers();
      if (request === listRequest.current) setServers(data);
    } catch (error) {
      if (request !== listRequest.current) return;
      setLoadError(errorMessage(error, 'Não foi possível carregar seus servidores. Verifique a conexão e tente novamente.'));
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }, []);

  useLayoutEffect(() => {
    mounted.current = true;
    void loadServers();
    return () => {
      mounted.current = false;
      ++listRequest.current;
    };
  }, [loadServers]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName || creating) return;
    setCreating(true);
    setCreateError('');
    try {
      const server = await createServer({
        ...(adult ? { is_adult: true } : {}),
        name: normalizedName,
        description: description.trim() || null,
      });
      navigate(`/servidores/${server.id}`);
    } catch (error) {
      setCreateError(errorMessage(error, 'Não foi possível criar o servidor. Verifique sua conexão e tente novamente.'));
    } finally {
      setCreating(false);
    }
  }

  async function handleAcceptInvite(event: FormEvent) {
    event.preventDefault();
    const serverId = Number(inviteServerId.trim());
    const token = inviteToken.trim();
    if (!Number.isSafeInteger(serverId) || serverId <= 0 || !token || acceptingInvite) {
      setInviteError('Informe um ID de servidor positivo e o token do convite.');
      return;
    }

    setAcceptingInvite(true);
    setInviteError('');
    setJoinedServerId(null);
    try {
      const membership = await acceptServerInvite(serverId, token);
      if (!mounted.current) return;
      setInviteToken('');
      setJoinedServerId(membership.server_id);
      void loadServers();
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ApiError) {
        if (error.status === 401) setInviteError('Sua sessão expirou. Entre novamente para aceitar o convite.');
        else if (error.status === 403) setInviteError(error.message || 'Sua conta não pode entrar neste servidor no momento.');
        else if (error.status === 404) setInviteError('Convite inválido ou servidor indisponível. Confira o ID e o token.');
        else if (error.status === 409) setInviteError(error.message || 'Este convite não pode mais ser utilizado.');
        else if (error.status === 422) setInviteError(error.message || 'Confira o ID do servidor e o token informados.');
        else setInviteError(error.message || 'Não foi possível aceitar o convite. Tente novamente.');
      } else {
        setInviteError('Não foi possível conectar à API para aceitar o convite. Tente novamente.');
      }
    } finally {
      if (mounted.current) setAcceptingInvite(false);
    }
  }

  return (
    <DashboardLayout title="Servidores" description="Acesse os servidores dos quais você participa." headerAction={(
      <a className="dashboard-create-button" href="#criar-servidor"><Plus size={16} /><span>Criar servidor</span></a>
    )}>
      <section className="server-page">
        <section className="server-intro">
          <div><span className="dashboard-eyebrow"><ShieldCheck size={14} /> COMUNIDADES COM CONTROLE</span><h2>Seus servidores.</h2><p>A lista mostra apenas servidores em que sua participação está ativa. Conhecer um identificador não concede acesso.</p></div>
          <span className="server-intro__mark"><Server size={24} /></span>
        </section>

        <section className="server-panel" aria-labelledby="accept-invite-title">
          <header className="server-panel__header"><div><h3 id="accept-invite-title">Entrar com convite</h3><p>Informe o ID do servidor e o token compartilhado com você.</p></div></header>
          <form className="server-create-form" onSubmit={event => void handleAcceptInvite(event)}>
            <label className="server-field"><span>ID do servidor</span><input inputMode="numeric" pattern="[0-9]*" value={inviteServerId} onChange={event => setInviteServerId(event.target.value)} required aria-label="ID do servidor do convite" placeholder="Ex.: 12" /></label>
            <label className="server-field"><span>Token do convite</span><input value={inviteToken} onChange={event => setInviteToken(event.target.value)} required autoComplete="off" aria-label="Token do convite" placeholder="Cole o token recebido" /></label>
            {inviteError && <p className="server-error" role="alert">{inviteError}</p>}
            {joinedServerId !== null && <p className="server-success" role="status">
              Entrada confirmada no servidor {joinedServerId}. {loading ? 'Atualizando sua lista…' : loadError ? 'Não foi possível atualizar sua lista.' : 'Sua lista foi atualizada.'}
            </p>}
            <button className="server-primary-button" type="submit" disabled={acceptingInvite || !inviteServerId.trim() || !inviteToken.trim()}>{acceptingInvite ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />} Aceitar convite</button>
          </form>
        </section>

        <section className="server-panel" aria-labelledby="server-list-title">
          <header className="server-panel__header"><div><h3 id="server-list-title">Seus espaços</h3><p>Servidores disponíveis para sua conta</p></div><button className="server-secondary-button" type="button" onClick={() => void loadServers()} disabled={loading}>Atualizar</button></header>
          {loading ? <div className="server-state" role="status"><LoaderCircle className="spin" size={19} />Carregando servidores…</div>
            : loadError ? <div className="server-state server-state--error" role="alert"><strong>{loadError}</strong><button type="button" className="server-secondary-button" onClick={() => void loadServers()}>Tentar novamente</button></div>
              : servers.length === 0 ? <div className="server-state server-state--empty"><Server size={23} /><strong>Você ainda não participa de servidores</strong><span>Crie um espaço ou aceite um convite válido para entrar em um servidor.</span></div>
                : <div className="server-list">{servers.map(server => <Link className="server-card" to={`/servidores/${server.id}`} key={server.id}>
                  <span className="server-card__icon"><Server size={19} /></span><span className="server-card__body"><strong>{server.name}</strong><span>{server.description || 'Sem descrição'}</span><small>{server.owner_id === user?.id ? 'Proprietário' : 'Membro ativo'} · Criado em {formatDate(server.created_at)}</small></span><ArrowRight size={17} className="server-card__arrow" />
                </Link>)}</div>}
        </section>

        <section className="server-panel" id="criar-servidor" aria-labelledby="create-server-title">
          <header className="server-panel__header"><div><h3 id="create-server-title">Criar servidor</h3><p>O criador se torna o proprietário do novo servidor.</p></div></header>
          <form className="server-create-form" onSubmit={event => void handleCreate(event)}>
            <label className="server-field"><span>Nome do servidor</span><input value={name} onChange={event => setName(event.target.value)} required minLength={1} maxLength={100} placeholder="Ex.: Comunidade SafeTalk" /></label>
            <label className="server-field"><span>Descrição <small>(opcional)</small></span><textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} placeholder="Conte um pouco sobre este espaço" /></label>
            {createError && <p className="server-error" role="alert">{createError}</p>}
            <label><input type="checkbox" checked={adult} onChange={e => setAdult(e.target.checked)} />Servidor +18 — esta classificação é permanente.</label>
            <button className="server-primary-button" type="submit" disabled={creating || !name.trim()}>{creating ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />} Criar servidor</button>
          </form>
        </section>
      </section>
    </DashboardLayout>
  );
}
