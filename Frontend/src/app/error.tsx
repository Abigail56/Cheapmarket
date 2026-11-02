"use client";

import { EmptyState } from "@/components/ui";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="container-page py-16">
      <EmptyState
        title="Something went wrong"
        action={
          <button type="button" className="btn-primary" onClick={reset}>
            Try again
          </button>
        }
      >
        We couldn&apos;t load this page. Please check your connection and try again.
      </EmptyState>
    </div>
  );
}
