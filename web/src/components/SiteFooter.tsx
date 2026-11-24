import Link from "next/link";
import { arena } from "@/lib/arena";
import { Logo, PAGES } from "./Logo";

export function SiteFooter() {
  const { site, stamp } = arena;
  return (
    <footer className="site-footer">
      <div className="wrap">
        <div className="footer-top">
          <Link href="/" className="brand"><Logo />{site.name}</Link>
          <nav aria-label="Footer">
            {PAGES.map((p) => <Link key={p.href} href={p.href}>{p.label}</Link>)}
            <Link href="/calibration">Calibration</Link>
            {site.repo_url && <a href={site.repo_url}>Source</a>}
          </nav>
        </div>
        <p className="footer-stamp">
          <span>Scenario set {stamp.scenarioSet || "–"}</span>
          <span>Code {stamp.code || "–"}</span>
          <span>{stamp.callsPlaced ? `Calls placed ${stamp.callsPlaced}` : "No calls yet"}</span>
          <span>The caller is a synthetic voice</span>
        </p>
      </div>
    </footer>
  );
}
