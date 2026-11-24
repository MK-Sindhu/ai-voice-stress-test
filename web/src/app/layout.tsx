import type { Metadata } from "next";
import { Anek_Devanagari, Bricolage_Grotesque, Geist_Mono, Hanken_Grotesk } from "next/font/google";
import { arena } from "@/lib/arena";
import "./globals.css";

const display = Bricolage_Grotesque({ variable: "--font-display", subsets: ["latin"] });
const body = Hanken_Grotesk({ variable: "--font-body", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-mono", subsets: ["latin"] });
const hindi = Anek_Devanagari({ variable: "--font-hindi", subsets: ["devanagari"] });

export const metadata: Metadata = {
  title: `${arena.site.name}: the caller built to break voice agents`,
  description:
    "A scripted caller stress-tests voice agents in Hindi, Hinglish and Indian English and publishes a leaderboard with a recording of every failure.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable} ${hindi.variable}`}>
      <body>{children}</body>
    </html>
  );
}
