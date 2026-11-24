import type { MetadataRoute } from "next";
import { arena } from "@/lib/arena";

export default function robots(): MetadataRoute.Robots {
  const base = arena.site.url?.replace(/\/$/, "");
  return { rules: { userAgent: "*", allow: "/" }, ...(base ? { sitemap: `${base}/sitemap.xml` } : {}) };
}
