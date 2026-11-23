# Adding a business (workspace)

A workspace is a folder under `workspaces/` named after its slug:

```
workspaces/my-business/
  workspace.yaml
  knowledge-base/        # Markdown documents (used by a later phase)
```

Start from `workspaces/northwind-academy/workspace.yaml`, a complete fictional example. Main sections:

| Key | Notes |
|---|---|
| `slug` | kebab-case, must equal the folder name |
| `profile` | name, tagline, website, contact email, timezone, optional `reference_prefix` (2-4 capitals) |
| `languages` | `default` plus `supported` (two-letter codes); every localized text needs the default language |
| `products[]` | id, name, summary, optional price/duration |
| `qualification` | `criteria[]` (id, weight, guide) and `tiers` (`hot_min` > `warm_min`) |
| `form.fields[]` | `type` is one of text, email, textarea, select, country, number, checkbox; exactly one field with `role: name`, one with `role: email`, at most one `role: free_text`; optional `section` groups consecutive fields under a heading |
| `privacy` | `version` is stored with each lead's consent; changing it forces visitors to re-accept |
| `cors.allowed_origins` | absolute `https://` origins of sites that may post to the API (`WEB_PUBLIC_ORIGIN` is added automatically) |
| `channels` | `email` only; `whatsapp.enabled: true` is rejected until it exists |

Then add the slug to `ENABLED_WORKSPACES`. Startup validates every workspace and exits with a list of
all problems (file, field path, message) if anything is wrong.

## Draft workspaces

`profile.draft: true` lets a workspace carry `TODO(david)` placeholders (the validator rejects them
otherwise). Draft workspaces are listed in the dashboard but their public form and intake return 404
unless `ALLOW_DRAFT_WORKSPACES=true`. `workspaces/david-moreno` is such a draft: only the three service
names are filled in and its knowledge base is empty on purpose.

## Embedding the form elsewhere

Any site listed in `cors.allowed_origins` can `POST` JSON to `/api/leads/{slug}` (see the OpenAPI
document at `/docs`). A copy-paste snippet guide arrives with the deployment phase.
