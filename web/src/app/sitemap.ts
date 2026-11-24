import type { MetadataRoute } from "next";
import { arena } from "@/lib/arena";

// Needs the public address of the site, set as site.url in params.yaml.
export default function sitemap(): MetadataRoute.Sitemap {
  const base = arena.site.url?.replace(/\/$/, "");
  if (!base) return [];
  const modified = arena.stamp.callsPlaced || undefined;
  return ["", "/leaderboard", "/scenarios", "/failures", "/method", "/calibration"].map((path) => ({
    url: `${base}${path}`, lastModified: modified,
  }));
}
