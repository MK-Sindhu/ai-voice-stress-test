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

## Where things are

| File | What it is |
|---|---|
| `src/app/page.tsx` | The home page: hero, the caller's seven tricks, leaderboard, scenario table, failures, method |
| `src/app/calibration/page.tsx` | Results of the fake and oracle agents |
| `src/app/globals.css` | The whole look: colours, type, layout, motion |
| `src/components/Field.tsx` | The grainy gradient with crossing rings behind the hero and the closing panel |
| `src/components/CallPlayer.tsx` | A call drawn as two lanes, with playback |
| `src/components/Failures.tsx` | The filterable list of failures |
| `src/components/Board.tsx` | Leaderboard rows and the scenario table |
| `src/lib/arena.ts` | Types for `arena.json` |

The site name, the "Source" link and the contact address come from `site:` in the repository's `params.yaml`.

## Deploy on Vercel

Import the repository and set **Root Directory** to `web`. Vercel detects Next.js; leave the build settings at their defaults. Every push to `main` redeploys.
