/**
 * Read a request body as text without ever holding more than `maxBytes`: chunks are counted as
 * they arrive and the stream is cancelled at the first byte over the limit. Returns null when the
 * body is too large (declared or actual). A missing or malformed Content-Length is not trusted:
 * the count comes from the bytes actually read.
 */
export async function readBoundedText(request: Request, maxBytes: number): Promise<string | null> {
  const declared = request.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > maxBytes) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => undefined);
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}
