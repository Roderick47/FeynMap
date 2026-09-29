/** Caller of imported JS implementation, even if adapter cannot resolve it. */
import { normalizeSeverity } from "./severity.js";

export function formatTicketAlert(ticket) {
  const severity = normalizeSeverity(ticket.priority);
  return severity + ": ticket assigned to " + ticket.owner;
}

export function formatUnrelatedInvoice(amount) {
  return "invoice " + amount;
}
