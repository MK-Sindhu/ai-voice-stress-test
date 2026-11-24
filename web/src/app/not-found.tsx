import Link from "next/link";

export default function NotFound() {
  return (
    <div className="wrap page not-found">
      <p className="tag">404</p>
      <h1>No answer on this line</h1>
      <p className="lead">The page you asked for does not exist. It may have moved when the site was reorganised.</p>
      <Link className="btn" href="/">Back to the home page</Link>
    </div>
  );
}
