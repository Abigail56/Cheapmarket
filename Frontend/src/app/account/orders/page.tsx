"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ChevronRight } from "@/components/icons";
import { EmptyState, PageLoading, PaymentBadge, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, money } from "@/lib/format";
import type { Order, Page } from "@/lib/types";

export default function OrdersPage() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<Order> | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<Page<Order>>(`/orders?page=${page}&size=10`)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(false);
        }
      })
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [page]);

  if (error) return <EmptyState title="Couldn't load your orders">Please refresh the page.</EmptyState>;
  if (!data) return <PageLoading />;
  if (!data.items.length) {
    return (
      <EmptyState
        title="No orders yet"
        action={
          <Link href="/shop" className="btn-primary">
            Start shopping
          </Link>
        }
      >
        Orders you place while signed in appear here.
      </EmptyState>
    );
  }

  return (
    <div className="space-y-4">
      <ul className="card divide-y divide-slate-100">
        {data.items.map((o) => (
          <li key={o.id}>
            <Link href={`/orders/${o.order_number}`} className="flex items-center gap-4 p-4 hover:bg-slate-50">
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-slate-900">{o.order_number}</p>
                <p className="text-sm text-slate-500">
                  {dateTime(o.created_at)} · {o.items.reduce((n, i) => n + i.quantity, 0)} items
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <StatusBadge status={o.status} />
                  <PaymentBadge status={o.payment_status} />
                </div>
              </div>
              <p className="font-bold tabular-nums">{money(o.total)}</p>
              <ChevronRight className="text-slate-400" />
            </Link>
          </li>
        ))}
      </ul>
      {data.pages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <button type="button" className="btn-secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <span className="text-sm text-slate-600">
            Page {data.page} of {data.pages}
          </span>
          <button
            type="button"
            className="btn-secondary"
            disabled={page >= data.pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
