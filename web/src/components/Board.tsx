import type { Agent, Cell, Column, Scenario } from "@/lib/arena";

// One row per agent: the headline score, then every other measurement as a tile.
export function Leaderboard({ agents, columns, ranked = true }: { agents: Agent[]; columns: Column[]; ranked?: boolean }) {
  const [main, ...rest] = columns;
  return (
    <ol className="board">
      {agents.map((agent, i) => {
        const score = agent.metrics[main.key];
        return (
          <li key={agent.id} className="row">
            <div className="row-head">
              {ranked && <span className="rank">{i + 1}</span>}
              <div>
                <h3>{agent.label}</h3>
                <p className="meta">{agent.id} · {agent.passes} {agent.passes === 1 ? "pass" : "passes"} · {agent.calls} calls</p>
              </div>
              <div className="score">
                <p className="score-value">{score.value}</p>
                <p className="score-name">{main.title.toLowerCase()}{score.footnote && ` · ${score.footnote}`}</p>
                {score.share !== null && <span className="meter meter-big"><i style={{ width: `${score.share * 100}%` }} /></span>}
              </div>
            </div>
            <dl className="tiles">
              {rest.map((c) => {
                const m = agent.metrics[c.key];
                return (
                  <div key={c.key} className="tile">
                    <dt>{c.title}</dt>
                    <dd>
                      <span className="tile-value">{m.value}</span>
                      {m.footnote && <span className="tile-note">{m.footnote}</span>}
                      {m.share !== null && (
                        <span className={`meter ${c.better === "higher" ? "meter-up" : "meter-down"}`}><i style={{ width: `${m.share * 100}%` }} /></span>
                      )}
                      {m.perPass.length > 0 && <span className="tile-note">per pass: {m.perPass.join(", ")}</span>}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </li>
        );
      })}
    </ol>
  );
}

export function Matrix({ agents, scenarios, matrix, families, link = true }: {
  agents: Agent[]; scenarios: Scenario[]; matrix: Record<string, Record<string, Cell>>;
  families: { key: string; name: string }[]; link?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table className="matrix">
        <thead>
          <tr><th>Scenario</th><th>Language</th>{agents.map((a) => <th key={a.id}>{a.id}</th>)}</tr>
        </thead>
        <tbody>
          {families.map((family) => {
            const rows = scenarios.filter((s) => s.family === family.key);
            if (!rows.length) return null;
            return [
              <tr key={family.key} className="family-row"><th colSpan={agents.length + 2}>{family.name}</th></tr>,
              ...rows.map((s) => (
                <tr key={s.id}>
                  <th scope="row" title={s.description}>{s.title}<span className="meta">{s.id}</span></th>
                  <td>{s.language}</td>
                  {agents.map((a) => {
                    const cell = matrix[a.id]?.[s.id];
                    if (!cell) return <td key={a.id} className="na">not run</td>;
                    const text = `${cell.passed}/${cell.total}${cell.untestable && !cell.passed ? " untestable" : ""}`;
                    return (
                      <td key={a.id} className={`m-${cell.kind}`}>
                        {cell.kind === "pass" || !link ? <span>{text}</span> : <a href={`#${a.id}--${s.id}`}>{text}</a>}
                      </td>
                    );
                  })}
                </tr>
              )),
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}
