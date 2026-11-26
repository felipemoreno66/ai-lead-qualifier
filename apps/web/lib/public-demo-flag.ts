/**
 * Public demo mode (docker-compose.public.yml): the dashboard stays open to anyone, the data is
 * fictional, and the agent runs the fake provider. Read at request time, never at build time.
 */
export function isPublicDemo(env: Record<string, string | undefined> = process.env): boolean {
  return env.PUBLIC_DEMO === "true";
}
