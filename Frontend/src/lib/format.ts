import type { OrderStatus, PaymentMethod, PaymentStatus } from "./types";

const naira = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  maximumFractionDigits: 2,
  minimumFractionDigits: 0,
});

export function money(value: number | null | undefined): string {
  return naira.format(Number(value ?? 0));
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export const ORDER_STEPS: OrderStatus[] = [
  "pending",
  "confirmed",
  "packed",
  "out_for_delivery",
  "delivered",
];

export const STATUS_LABEL: Record<OrderStatus, string> = {
  pending: "Order placed",
  confirmed: "Confirmed",
  packed: "Packed",
  out_for_delivery: "On the way",
  delivered: "Delivered",
  cancelled: "Cancelled",
};

export const PAYMENT_METHOD_LABEL: Record<PaymentMethod, string> = {
  card: "Card (online)",
  cod: "Pay on delivery",
  transfer: "Bank transfer",
};

export const PAYMENT_STATUS_LABEL: Record<PaymentStatus, string> = {
  unpaid: "Not paid yet",
  paid: "Paid",
  failed: "Payment failed",
  refunded: "Refunded",
};

// The API stores phones as +234...; show them the way Nigerians write them
export function localPhone(phone: string | null | undefined): string {
  if (!phone) return "";
  return phone.startsWith("+234") ? "0" + phone.slice(4) : phone;
}
