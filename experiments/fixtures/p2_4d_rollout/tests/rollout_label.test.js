import { formatRolloutLabel } from "../client/rollout_label.js";

export function testRolloutLabel() {
  const value = formatRolloutLabel(" CANARY ", 25);
  if (value !== "ROLLOUT canary:25%") {
    throw new Error(`unexpected rollout label: ${value}`);
  }
}
