#!/usr/bin/env node
// Generates the argon2id hash for ADMIN_PASSWORD_HASH. The password is read from the terminal
// without echo (or from stdin when piped) and is never written anywhere.
//
//   pnpm hash-password
//   printf '%s' "$PASSWORD" | pnpm hash-password
import { hash } from "@node-rs/argon2";

const MIN_LENGTH = 12;

function readSecret(prompt) {
  return new Promise((resolve, reject) => {
    const { stdin, stderr } = process;
    if (!stdin.isTTY) {
      let data = "";
      stdin.setEncoding("utf8");
      stdin.on("data", (chunk) => (data += chunk));
      stdin.on("end", () => resolve(data.replace(/\r?\n$/, "")));
      stdin.on("error", reject);
      return;
    }
    stderr.write(prompt);
    let value = "";
    stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding("utf8");
    const onData = (key) => {
      for (const char of key) {
        if (char === "\u0003") process.exit(130); // Ctrl+C
        if (char === "\r" || char === "\n") {
          stdin.setRawMode(false);
          stdin.pause();
          stdin.off("data", onData);
          stderr.write("\n");
          return resolve(value);
        }
        if (char === "\u007f" || char === "\b") value = value.slice(0, -1);
        else value += char;
      }
    };
    stdin.on("data", onData);
  });
}

const password = await readSecret("New admin password: ");
if (process.stdin.isTTY) {
  const again = await readSecret("Repeat it: ");
  if (again !== password) {
    console.error("The passwords do not match.");
    process.exit(1);
  }
}
if (password.length < MIN_LENGTH) {
  console.error(`Use at least ${MIN_LENGTH} characters.`);
  process.exit(1);
}
const encoded = await hash(password, { algorithm: 2 }); // 2 = Argon2id
// Single quotes: Docker Compose and shells would otherwise expand the "$" signs in the hash.
console.log(`ADMIN_PASSWORD_HASH='${encoded}'`);
