"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { HOME, type Role } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Spinner, cx } from "./ui";

export type NavItem = { href: string; label: string };

/** Client-side route guard + layout. The API enforces RBAC independently; this only steers the UI. */
export function RoleShell({
  role,
  title,
  nav,
  children,
}: {
  role: Role;
  title: string;
  nav: NavItem[];
  children: React.ReactNode;
}) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const path = usePathname();

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (user.role !== role) router.replace(HOME[user.role]);
  }, [user, loading, role, router]);

  if (loading || !user || user.role !== role) return <Spinner label="Checking your session" />;

  return (
    <div className="min-h-screen md:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2"
      >
        Skip to content
      </a>
      <aside className="border-b border-slate-300 bg-white md:w-56 md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-3 md:block">
          <p className="text-sm font-bold text-blue-800">{title}</p>
          <p className="hidden text-xs text-slate-600 md:block">{user.full_name}</p>
        </div>
        <nav
          aria-label={`${title} navigation`}
          className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0"
        >
          {nav.map((n) => {
            const active = path === n.href || (n.href !== HOME[role] && path.startsWith(n.href));
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "whitespace-nowrap rounded px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600",
                  active ? "bg-blue-100 font-semibold text-blue-900" : "text-slate-800 hover:bg-slate-100",
                )}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="space-y-2 p-3">
          <Link
            href="/mfa"
            className="block text-center text-xs text-slate-600 hover:text-blue-800 hover:underline"
          >
            Two-factor auth (MFA)
          </Link>
          <Link
            href="/change-password"
            className="block text-center text-xs text-slate-600 hover:text-blue-800 hover:underline"
          >
            Change password
          </Link>
          <Button
            variant="secondary"
            className="w-full"
            onClick={async () => {
              await logout();
              router.replace("/login");
            }}
          >
            Sign out
          </Button>
        </div>
      </aside>
      <main id="main" className="flex-1 space-y-4 p-4 md:p-6">
        {children}
      </main>
    </div>
  );
}
