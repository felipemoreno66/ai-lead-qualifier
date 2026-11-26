import { connection } from "next/server";
import { isPublicDemo } from "@/lib/public-demo-flag";

/** Shown on every page of the public demo so nobody mistakes it for a real instance. */
export async function PublicDemoBanner() {
  await connection(); // read the flag per request, not at build time
  if (!isPublicDemo()) return null;
  return (
    <p className="demo-bar" role="note">
      <b>Public demo</b>
      <span>Fictional data, resets every night. Please do not enter real personal information.</span>
    </p>
  );
}
