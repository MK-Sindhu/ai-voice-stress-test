import Link from "next/link";
import { arena } from "@/lib/arena";

export function Logo() {
  return (
    <svg viewBox="0 0 28 22" aria-hidden="true" className="logo">
      <rect x="0" y="1" width="16" height="8" rx="4" fill="#9da8ff" />
      <rect x="10" y="13" width="18" height="8" rx="4" fill="#f7a72b" />
    </svg>
  );
}

export function Nav({ links }: { links: { href: string; label: string }[] }) {
  const { site } = arena;
  return (
    <header className="nav">
      <Link href="/" className="brand"><Logo />{site.name}</Link>
      <nav aria-label="Sections">
        {links.map((l) => <Link key={l.href} href={l.href}>{l.label}</Link>)}
      </nav>
      {site.repo_url ? <a className="btn btn-glass btn-small" href={site.repo_url}>Source</a> : <span />}
    </header>
  );
}

export function Footer() {
  const { site, stamp } = arena;
  return (
    <footer className="footer">
      <div className="wrap">
        <span className="brand"><Logo />{site.name}</span>
        <span>scenario set {stamp.scenarioSet || "–"}</span>
        <span>code {stamp.code || "–"}</span>
        <span>{stamp.callsPlaced ? `calls placed ${stamp.callsPlaced}` : "no calls yet"}</span>
        <span>the caller is a synthetic voice</span>
      </div>
    </footer>
  );
}
