export const PAGES = [
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/failures", label: "Failures" },
  { href: "/method", label: "Method" },
];

export function Logo() {
  return (
    <svg viewBox="0 0 30 22" aria-hidden="true" className="logo">
      <rect x="0" y="1" width="18" height="8" fill="var(--caller)" />
      <rect x="10" y="13" width="20" height="8" fill="var(--agent)" />
    </svg>
  );
}
