import { toNextJsHandler } from "better-auth/next-js";
import { isPublicPath } from "@/lib/auth/dashboard-guard";
import { authEnv, getAuth } from "@/lib/auth/session";
import { authMode } from "@/lib/auth/mode";

export const dynamic = "force-dynamic";

const noStore = { "Cache-Control": "no-store" };

/** Better Auth serves many endpoints; only the sign-in and sign-out the login page uses are exposed. */
async function handler(request: Request): Promise<Response> {
  if (!isPublicPath(new URL(request.url).pathname)) {
    return Response.json({ title: "Not found" }, { status: 404, headers: noStore });
  }
  if (authMode(authEnv()) !== "session") {
    return Response.json({ title: "Login is not configured" }, { status: 503, headers: noStore });
  }
  const auth = await getAuth();
  const response = await toNextJsHandler(auth).POST(request);
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export { handler as POST };
