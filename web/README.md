# The website

A Next.js site (App Router, TypeScript) that shows the results of the stress-test arena.

It holds no numbers of its own. Everything it displays comes from two things that `arena report` writes from the recorded calls:

- `src/content/arena.json`: the leaderboard, scenarios, every failure with its timeline, and the calibration results.
- `public/audio/`: the failure recordings.

Do not edit those by hand. To change what the site shows, run the pipeline (`uv run dvc repro` in the repository root), then commit.

## Run it

```
npm install
npm run dev        # http://localhost:3000
npm run build      # what the host runs
npm run lint
```

## Pages

| Address | File | What it shows |
|---|---|---|
| `/` | `src/app/page.tsx` | Short landing page: headline, a replay of one real call between two summary cards, the standings, and links to the rest |
| `/leaderboard` | `src/app/leaderboard/page.tsx` | Every measurement for every agent |
| `/scenarios` | `src/app/scenarios/page.tsx` | What the caller does in each kind of scenario, and results scenario by scenario |
| `/failures` | `src/app/failures/page.tsx` | Every failed call with its recording. `/failures#<agent>--<scenario>` opens one call |
| `/method` | `src/app/method/page.tsx` | How the measuring was checked, definitions, caveats |
| `/calibration` | `src/app/calibration/page.tsx` | Results of the fake and oracle agents |
| any other | `src/app/not-found.tsx` | The 404 page |

`src/app/layout.tsx` holds what every page shares: fonts, the header with the current page marked, the footer, the skip link and the default page title and description. `sitemap.ts` and `robots.ts` produce `/sitemap.xml` and `/robots.txt`; the sitemap is empty until `site.url` is set.

## Components

| File | What it is |
|---|---|
| `src/app/globals.css` | The whole look: colours, type, layout, motion |
| `src/components/Replay.tsx` | The card on the landing page that replays one call: waveform, the caller's words, and a flag |
| `src/components/Wave.tsx` | A call drawn as a waveform: caller above the line, agent below |
| `src/components/CallPlayer.tsx` | A call's waveform with playback |
| `src/components/Failures.tsx` | The filterable list of failures |
| `src/components/Board.tsx` | The standings, the full leaderboard and the scenario table |
| `src/components/SiteHeader.tsx`, `SiteFooter.tsx`, `PageHead.tsx` | Shared page furniture |
| `src/lib/arena.ts` | Types for `arena.json` |

The site name, its public address, the "Source" link and the contact address come from `site:` in the repository's `params.yaml`.

## Deploy on Vercel

Import the repository and set **Root Directory** to `web`. Vercel detects Next.js; leave the build settings at their defaults. Every push to `main` redeploys.
