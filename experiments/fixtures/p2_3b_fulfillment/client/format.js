import { normalizeStatus } from "./status.js";

export function formatShipmentStatus(value) {
  return `SHIPMENT:${normalizeStatus(value)}`;
}
