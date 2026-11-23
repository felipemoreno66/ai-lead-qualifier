// Prepares files for `n8n import:*` at container start.
// Workflows are committed WITHOUT credentials; this script writes the Mailpit SMTP credential
// (no password, local sink only) and attaches it to the email nodes in a temporary copy.
const fs = require("node:fs");
const path = require("node:path");

const SRC = path.join(__dirname, "workflows");
const OUT = "/tmp/n8n-import";
const CREDENTIAL = { id: "mailpitSmtp0001", name: "Mailpit SMTP" };

fs.mkdirSync(path.join(OUT, "workflows"), { recursive: true });
fs.writeFileSync(
  path.join(OUT, "credentials.json"),
  JSON.stringify([
    {
      ...CREDENTIAL,
      type: "smtp",
      data: {
        user: "",
        password: "",
        host: process.env.SMTP_HOST || "mailpit",
        port: Number(process.env.SMTP_PORT || 1025),
        secure: false,
        disableStartTls: true,
      },
    },
  ]),
);

for (const file of fs.readdirSync(SRC).filter((f) => f.endsWith(".json"))) {
  const workflow = JSON.parse(fs.readFileSync(path.join(SRC, file), "utf8"));
  for (const node of workflow.nodes) {
    if (node.type === "n8n-nodes-base.emailSend") node.credentials = { smtp: CREDENTIAL };
  }
  fs.writeFileSync(path.join(OUT, "workflows", file), JSON.stringify(workflow));
}
console.log("n8n import files ready");
