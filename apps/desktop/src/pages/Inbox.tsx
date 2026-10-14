import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import type { Ticket } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";
import { Picture } from "../ui/Picture";

/** Ends with one full stop, whether or not the API's words had one. */
const sentence = (s: string) => (/[.!?]$/.test(s) ? s : `${s}.`);

/** Tickets waiting for a manager's check, oldest first. */
export function Inbox() {
  const tickets = useLoad(() => api.get<Ticket[]>("/v1/tickets"), []);
  const [open, setOpen] = useState<number | null>(null);
  // another manager decided the one that was open: say so, as it leaves the list
  const [taken, setTaken] = useState<string | null>(null);
  const ticket = tickets.data?.find((t) => t.id === open);

  return (
    <main className="page">
      <h1>Inbox</h1>
      <div className="small">Tickets and licences people have sent in. Check each against its photos, then approve it or send it back with a reason.</div>
      <Problem error={tickets.error} />
      {taken && <div className="msg r" role="status">{taken}</div>}
      {tickets.data?.length === 0 && <div className="card small">Nothing waiting. New tickets show here as people send them in.</div>}
      {tickets.data && tickets.data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Person</th><th>Ticket</th><th>Number</th><th>Card good until</th><th>Sent</th></tr></thead>
          <tbody>
            {tickets.data.map((t) => (
              <tr key={t.id} className="click" onClick={() => { setTaken(null); setOpen(t.id); }}>
                <td><button type="button" className="rowbtn" onClick={() => { setTaken(null); setOpen(t.id); }}>
                  <b>{t.person.name}</b><span className="small block">{t.person.code}</span></button></td>
                <td>{t.competency.name}</td>
                <td>{t.number}</td>
                <td>{t.expires_on ? formatDate(t.expires_on) : "Doesn't run out"}</td>
                <td className="small">{formatDate(t.created_at.slice(0, 10))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {ticket && (
        <TicketDrawer key={ticket.id} ticket={ticket} onClose={() => setOpen(null)}
                      onDecided={() => { setOpen(null); tickets.reload(); }}
                      onTaken={(why) => { setOpen(null); setTaken(why); tickets.reload(); }} />
      )}
    </main>
  );
}

function TicketDrawer({ ticket, onClose, onDecided, onTaken }: {
  ticket: Ticket; onClose: () => void; onDecided: () => void; onTaken: (why: string) => void;
}) {
  const { me } = useAuth();
  const [reason, setReason] = useState("");
  const action = useAction();
  const path = `/v1/tickets/${ticket.id}`;
  const own = me?.code === ticket.person.code;

  async function decide(fn: () => Promise<unknown>) {
    let taken: string | null = null;
    const done = await action.run(async () => {
      try {
        await fn();
      } catch (e) {
        // 409 decided: another manager got there first
        if (!(e instanceof ApiError && e.status === 409 && e.code === "decided")) throw e;
        taken = `Another manager got there first: ${sentence(e.message)}`;
      }
    });
    if (taken) onTaken(taken);
    else if (done) onDecided();
  }

  function reject(e: FormEvent) {
    e.preventDefault();
    void decide(() => api.post(`${path}/reject`, { reason: reason.trim() }));
  }

  return (
    <Drawer title={`${ticket.competency.name}: ${ticket.person.name}`} sub={`${ticket.person.code} · sent ${formatDate(ticket.created_at.slice(0, 10))}`} onClose={onClose}
            focus="dialog">
      <dl className="card grid grid-cols-2 gap-2 text-sm">
        <dt className="small">Number</dt><dd className="m-0"><b>{ticket.number}</b></dd>
        <dt className="small">Card good until</dt><dd className="m-0"><b>{ticket.expires_on ? formatDate(ticket.expires_on) : "Doesn't run out"}</b></dd>
      </dl>
      <section className="flex flex-col gap-2" aria-label="Photos">
        <div className="eyebrow">Front</div>
        <Picture upload={ticket.front} label="The front" width={480} />
        {ticket.back && <><div className="eyebrow">Back</div><Picture upload={ticket.back} label="The back" width={480} /></>}
      </section>
      <Problem error={action.error} />
      {own ? (
        <div className="msg r">Nobody verifies their own ticket: ask another manager.</div>
      ) : (
        <>
          <div className="small">Approving records it as current until the card's date, from today.</div>
          <button type="button" className="btn primary" disabled={action.busy}
                  onClick={() => void decide(() => api.post(`${path}/approve`))}>Approve</button>
          <form className="card flex flex-col gap-3" onSubmit={reject}>
            <div className="eyebrow">Send it back</div>
            <label className="label">Reason (they see this)
              <input className="field" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)}
                     placeholder="e.g. the photo is blurry: take it again in good light" required />
            </label>
            <button type="submit" className="btn danger" disabled={action.busy || !reason.trim()}>Reject</button>
          </form>
        </>
      )}
    </Drawer>
  );
}
