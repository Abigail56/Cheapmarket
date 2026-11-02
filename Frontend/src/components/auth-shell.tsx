// Shared frame for sign-in, sign-up and password pages

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="relative isolate overflow-hidden bg-brand-950">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/images/hero.jpg" alt="" className="absolute inset-0 -z-10 h-full w-full object-cover" />
      <div className="absolute inset-0 -z-10 bg-brand-950/65" />
      <div className="container-page flex min-h-[calc(100vh-10rem)] items-center justify-center py-12 sm:py-20">
        <div className="w-full max-w-md">
          <div className="space-y-6 rounded-2xl bg-white p-6 shadow-2xl sm:p-8">
            <div>
              <h1 className="text-3xl font-semibold text-slate-900">{title}</h1>
              {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
            </div>
            {children}
          </div>
          {footer && <div className="auth-footer mt-5 text-center text-sm text-white">{footer}</div>}
        </div>
      </div>
    </div>
  );
}

// Only follow ?next= to pages on this site (never to another domain)
export function safeNext(next: string | null, fallback = "/account"): string {
  // "//x" and "/\x" are both read by browsers as another site
  return next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") ? next : fallback;
}
