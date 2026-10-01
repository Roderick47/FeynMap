import { normalizeChannel } from "./channel.js";

export function formatRolloutLabel(channel, percent) {
  return `ROLLOUT ${normalizeChannel(channel)}:${percent}%`;
}
