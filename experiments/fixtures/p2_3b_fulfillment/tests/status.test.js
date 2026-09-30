import { formatShipmentStatus } from "../client/format.js";

export function testFormatShipmentStatus() {
  if (formatShipmentStatus(" packed ") !== "SHIPMENT:PACKED") {
    throw new Error("shipment status normalization failed");
  }
}
