import Link from "next/link";

export default function Home() {
  return (
    <main>
      <h1>AI Lead Qualifier</h1>
      <p>Open-source mini CRM. A person approves every reply.</p>
      <Link href="/dashboard">Open the dashboard</Link>
    </main>
  );
}
