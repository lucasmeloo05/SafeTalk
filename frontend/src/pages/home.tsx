import { useState } from 'react';
import {
  Plus,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { ConversationWorkspace } from '@/components/conversation-workspace';
import { DashboardLayout } from '@/components/dashboard-layout';

export function HomePage() {
  const [createConversationOpen, setCreateConversationOpen] = useState(false);

  return (
    <DashboardLayout
      title="Conversas"
      description="Seu espaço para conversas privadas e tranquilas."
      headerAction={(
        <button className="dashboard-create-button" type="button" onClick={() => setCreateConversationOpen(true)}>
          <Plus size={17} /> <span>Nova conversa</span>
        </button>
      )}
    >
      <section className="dashboard-welcome" aria-labelledby="welcome-title">
        <div className="dashboard-welcome__copy">
          <span className="dashboard-eyebrow"><Sparkles size={14} /> SEU ESPAÇO ESTÁ PRONTO</span>
          <h2 id="welcome-title">Conversas com mais tranquilidade.</h2>
          <p>Um lugar pensado para conversas com mais privacidade, segurança e tranquilidade.</p>
        </div>
        <div className="dashboard-welcome__seal" aria-hidden="true">
          <span className="dashboard-welcome__seal-ring"><ShieldCheck size={25} /></span>
          <span>CONVERSAS<br />COM CUIDADO</span>
        </div>
      </section>
      <ConversationWorkspace
        createDialogOpen={createConversationOpen}
        onCreateDialogOpenChange={setCreateConversationOpen}
      />
    </DashboardLayout>
  );
}
