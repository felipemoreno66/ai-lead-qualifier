export function PublicShell({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="public">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="pub-top">
        <span className="brand">
          <span className="mark" aria-hidden="true" />
          {name}
        </span>
      </header>
      <main id="main">{children}</main>
    </div>
  );
}
