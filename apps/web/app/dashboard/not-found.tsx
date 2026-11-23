import Link from "next/link";

export default function NotFound() {
  return (
    <section className="empty">
      <h1>Lead not found</h1>
      <p>It may have been deleted. Go back to the list to see the current leads.</p>
      <Link className="btn" href="/dashboard">
        Back to leads
      </Link>
    </section>
  );
}
