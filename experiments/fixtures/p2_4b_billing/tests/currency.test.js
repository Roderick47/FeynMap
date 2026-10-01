import { normalizeCurrency } from "../client/currency.js";
import { formatPaymentLabel } from "../client/label.js";

export function testCurrencyFormatting() {
  if (normalizeCurrency(" pgk ") !== "PGK") throw new Error("normalization failed");
  if (formatPaymentLabel(" usd ", 25) !== "PAY USD:25") throw new Error("label failed");
}
