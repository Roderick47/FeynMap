import { normalizeCurrency } from "./currency.js";

export function formatPaymentLabel(code, amount) {
  return `PAY ${normalizeCurrency(code)}:${amount}`;
}
