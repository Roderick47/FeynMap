/** Distinct JS module; source-grounded severity vocabulary. */
export function normalizeSeverity(level) {
  if (level === "urgent") return "HIGH";
  if (level === "normal") return "MEDIUM";
  return "LOW";
}

export function irrelevantPriceLabel(amount) {
  return "K" + amount;
}
