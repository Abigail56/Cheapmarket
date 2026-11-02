"use client";

import { useRouter } from "next/navigation";

import { PhoneGate } from "@/components/phone-gate";
import { orderAccessStore } from "@/lib/storage";

export default function TrackPage() {
  const router = useRouter();
  return (
    <div className="container-page py-12">
      <PhoneGate
        onFound={(order, phone) => {
          orderAccessStore.set(order.order_number, { phone });
          router.push(`/orders/${order.order_number}`);
        }}
      />
    </div>
  );
}
