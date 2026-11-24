"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo, PAGES } from "./Logo";

export function SiteHeader({ name, repo }: { name: string; repo: string }) {
  const pathname = usePathname();
  return (
    <header className="site-header">
      <div className="wrap">
        <Link href="/" className="brand" aria-label={`${name}, home`}><Logo />{name}</Link>
        <nav aria-label="Main">
          {PAGES.map((p) => (
            <Link key={p.href} href={p.href} aria-current={pathname.startsWith(p.href) ? "page" : undefined}>{p.label}</Link>
          ))}
        </nav>
        {repo && <a className="header-source" href={repo}>Source</a>}
      </div>
    </header>
  );
}
