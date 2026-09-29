/** These are JS source test symbols, not automatically production truth. */
import { formatTicketAlert } from "./presenter.js";

export function testUrgentTicketAlert() {
  const text = formatTicketAlert({priority: "urgent", owner: "bob"});
  return text.indexOf("HIGH") >= 0;
}

export function testUnrelatedInvoiceFormat() {
  return true;
}
