"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { PUBLIC_PATHS, useAuth } from "@/lib/auth";
import { Loading } from "./ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard", exact: true },
  { href: "/domains", label: "Domains" },
  { href: "/hosting", label: "Hosting accounts" },
  { href: "/registrars", label: "Registrars" },
  { href: "/notifications", label: "Notification history" },
  { href: "/", label: "Public overview", exact: true },
];

const SETTINGS_NAV = [
  { href: "/settings/email", label: "Email" },
  { href: "/settings/integrations", label: "Provider integrations" },
  { href: "/settings/admins", label: "Administrators" },
  { href: "/settings", label: "General", exact: true },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [pathname]);

  if (PUBLIC_PATHS.includes(pathname)) return <>{children}</>;
  if (loading || !user) return <Loading label="Checking your session…" />;

  const isActive = (href: string, exact?: boolean) => (exact ? pathname === href : pathname.startsWith(href));
  const link = (item: { href: string; label: string; exact?: boolean }) => (
    <Link
      key={item.href}
      href={item.href}
      className={`nav-link${isActive(item.href, item.exact) ? " active" : ""}`}
      aria-current={isActive(item.href, item.exact) ? "page" : undefined}
    >
      {item.label}
    </Link>
  );

  return (
    <>
      <div className="mobile-bar">
        <span className="brand-mark">Domain Monitor</span>
        <button className="btn small" aria-expanded={open} aria-controls="sidebar" onClick={() => setOpen(!open)}>
          {open ? "Close" : "Menu"}
        </button>
      </div>
      <div className="shell">
        <nav id="sidebar" className={`sidebar${open ? " open" : ""}`} aria-label="Main">
          <div className="brand">
            <span className="brand-mark">Domain Monitor</span>
            <small>Domains & hosting expirations</small>
          </div>
          {NAV.map(link)}
          <div className="nav-section">Settings</div>
          {SETTINGS_NAV.map(link)}
          <div className="sidebar-footer">
            <span title={user.email}>Signed in as {user.email}</span>
            <button className="btn small" onClick={logout}>
              Sign out
            </button>
          </div>
        </nav>
        <main className="main" id="main">
          {children}
        </main>
      </div>
    </>
  );
}
