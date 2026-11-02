import Link from "next/link";

import { EmptyState } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="container-page py-16">
      <EmptyState
        title="We couldn't find that page"
        action={
          <Link href="/shop" className="btn-primary">
            Go to the shop
          </Link>
        }
      >
        The product may have sold out or the link may be wrong.
      </EmptyState>
    </div>
  );
}
