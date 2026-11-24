// The top of every inner page: what the page is, in one line and one paragraph.
export function PageHead({ tag, title, children }: { tag: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="page-head">
      <p className="tag">{tag}</p>
      <h1>{title}</h1>
      {children && <p className="lead">{children}</p>}
    </div>
  );
}
