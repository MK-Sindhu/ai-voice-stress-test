import type { Metadata } from "next";
import { Hind, JetBrains_Mono, Teko } from "next/font/google";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { arena } from "@/lib/arena";
import "./globals.css";

// Teko and Hind come from the same foundry and both carry Devanagari, so
// Hindi and English are set in matching letterforms.
const display = Teko({ variable: "--font-display", subsets: ["latin", "devanagari"], weight: ["400", "500", "600"] });
const body = Hind({ variable: "--font-body", subsets: ["latin", "devanagari"], weight: ["400", "500", "600"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"], weight: ["400", "500", "700"] });

const { site } = arena;
const description =
  "A scripted caller stress-tests voice agents in Hindi, Hinglish and Indian English and publishes a leaderboard with a recording of every failure.";

export const metadata: Metadata = {
  metadataBase: site.url ? new URL(site.url) : undefined,
  title: { default: `${site.name}: the caller from hell for voice agents`, template: `%s · ${site.name}` },
  description,
  openGraph: { title: `${site.name}: the caller from hell for voice agents`, description, type: "website", siteName: site.name },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <SiteHeader name={site.name} repo={site.repo_url} />
        <main id="main">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
