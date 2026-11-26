"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { countryOptions } from "@/lib/forms/countries";
import type { FormFieldDef } from "@/lib/forms/build-lead-schema";
import type { PublicWorkspaceConfig } from "@/lib/api/types";
import { localized, ui } from "@/lib/i18n";
import { validateAnswers, type FieldErrors, type RawValues } from "./validate";

type Props = { config: PublicWorkspaceConfig; apiBase: string; initialLocale: string; demoNotice?: boolean };

const AUTOCOMPLETE: Record<string, string> = { name: "name", email: "email" };
const PILL_MAX_OPTIONS = 5;

export function ApplyForm({ config, apiBase, initialLocale, demoNotice = false }: Props) {
  const router = useRouter();
  const [locale, setLocale] = useState(initialLocale);
  const t = ui(locale);
  const fallback = config.default_language;
  const [values, setValues] = useState<RawValues>({});
  const [errors, setErrors] = useState<FieldErrors>({});
  const [consent, setConsent] = useState(false);
  const [consentError, setConsentError] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const renderedAt = useRef<string>("");
  const summaryRef = useRef<HTMLDivElement>(null);
  const uid = useId();

  useEffect(() => {
    // Keep <html lang> in step with the language the form is shown in (WCAG 3.1.2).
    const previous = document.documentElement.lang;
    document.documentElement.lang = locale;
    return () => {
      document.documentElement.lang = previous;
    };
  }, [locale]);

  useEffect(() => {
    renderedAt.current = new Date().toISOString();
  }, []);

  // Country names are localized with the browser's ICU data, which can differ from the server's,
  // so the options are filled in after mount to keep hydration identical.
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const countries = useMemo(() => (mounted ? countryOptions(locale) : []), [mounted, locale]);
  const sections = useMemo(() => {
    const groups: { title: string; fields: FormFieldDef[] }[] = [];
    for (const field of config.form.fields) {
      const title = field.section ? localized(field.section, fallback, fallback) : "";
      const last = groups.at(-1);
      if (last && last.title === title) last.fields.push(field);
      else groups.push({ title, fields: [field] });
    }
    return groups;
  }, [config.form.fields, fallback]);

  const label = (f: FormFieldDef) => localized(f.label, locale, fallback);
  const set = (id: string, value: string | boolean) => {
    setValues((v) => ({ ...v, [id]: value }));
    if (errors[id])
      setErrors((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
  };

  const failWith = (fieldErrors: FieldErrors, consentMissing: boolean, general: string | null) => {
    setErrors(fieldErrors);
    setConsentError(consentMissing);
    setFormError(general);
    requestAnimationFrame(() => summaryRef.current?.focus());
  };

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const { answers, errors: found } = validateAnswers(config.form.fields, values, locale);
    if (Object.keys(found).length || !consent) {
      failWith(found, !consent, null);
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const response = await fetch(`${apiBase}/api/leads/${config.slug}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fields: answers,
          consent: true,
          consent_notice_version: config.privacy.version,
          locale,
          hp_company_website: honeypot,
          form_rendered_at: renderedAt.current,
        }),
      });
      if (response.status === 202) {
        const body = (await response.json()) as { reference: string };
        router.push(`/w/${config.slug}/apply/thanks?ref=${encodeURIComponent(body.reference)}&lang=${locale}`);
        return;
      }
      const problem = (await response.json().catch(() => ({}))) as {
        type?: string;
        errors?: { loc: string[]; msg: string }[];
      };
      if (response.status === 429) failWith({}, false, t.rateLimited);
      else if (problem.type === "urn:lead-qualifier:consent_outdated") failWith({}, false, t.consentOutdated);
      else if (response.status === 422) {
        const serverErrors: FieldErrors = {};
        for (const e of problem.errors ?? []) if (e.loc[0] === "fields" && e.loc[1]) serverErrors[e.loc[1]] = t.invalid;
        failWith(serverErrors, false, Object.keys(serverErrors).length ? null : t.genericError);
      } else failWith({}, false, t.genericError);
    } catch {
      failWith({}, false, t.networkError);
    } finally {
      setSubmitting(false);
    }
  }

  const errorIds = Object.keys(errors);
  const showSummary = errorIds.length > 0 || consentError || formError !== null;
  const byId = new Map(config.form.fields.map((f) => [f.id, f]));

  return (
    <div className="apply" lang={locale}>
      <div className="intro">
        <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 20 }}>
          {config.languages.length > 1 && (
            <div className="langs" role="group" aria-label={t.language} style={{ marginLeft: 0 }}>
              {config.languages.map((code) => (
                <button
                  key={code}
                  type="button"
                  className="seg"
                  aria-pressed={locale === code}
                  lang={code}
                  onClick={() => setLocale(code)}
                >
                  {code.toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>
        <h1>{t.applyTitle(config.name)}</h1>
        <p className="lead">{config.tagline}. {t.applyLead}</p>
        {demoNotice && (
          <p className="hint" role="note">
            Fictional demo: use made-up details, not your real name, email or phone number.
          </p>
        )}
      </div>

      <form className="form" onSubmit={onSubmit} noValidate aria-busy={submitting}>
        <div className="hp" aria-hidden="true">
          <label htmlFor={`${uid}-hp`}>Company website</label>
          <input
            id={`${uid}-hp`}
            name="hp_company_website"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(e) => setHoneypot(e.target.value)}
          />
        </div>

        {showSummary && (
          <div className="form-alert" role="alert" tabIndex={-1} ref={summaryRef}>
            <h2>{formError ?? t.fixFields}</h2>
            {(errorIds.length > 0 || consentError) && (
              <ul>
                {errorIds.map((id) => (
                  <li key={id}>
                    <a href={`#${uid}-${id}`}>{byId.get(id) ? label(byId.get(id)!) : id}</a>: {errors[id]}
                  </li>
                ))}
                {consentError && (
                  <li>
                    <a href={`#${uid}-consent`}>{t.consentLabel}</a>
                  </li>
                )}
              </ul>
            )}
          </div>
        )}

        {sections.map((section, index) => (
          <fieldset key={section.title || index}>
            {section.title && (
              <legend>
                {sections.length > 1 && <span className="step num">{t.stepOf(index + 1, sections.length)}</span>}
                {localized(section.fields[0].section, locale, fallback)}
              </legend>
            )}
            {section.fields.map((field) => (
              <FieldControl
                key={field.id}
                field={field}
                inputId={`${uid}-${field.id}`}
                locale={locale}
                fallback={fallback}
                value={values[field.id]}
                error={errors[field.id]}
                countries={countries}
                onChange={(v) => set(field.id, v)}
              />
            ))}
          </fieldset>
        ))}

        <div className="consent">
          <label className="check" htmlFor={`${uid}-consent`}>
            <input
              id={`${uid}-consent`}
              type="checkbox"
              checked={consent}
              aria-invalid={consentError || undefined}
              aria-describedby={`${uid}-notice`}
              onChange={(e) => {
                setConsent(e.target.checked);
                if (e.target.checked) setConsentError(false);
              }}
            />
            <span>{t.consentLabel}</span>
          </label>
          <p className="hint" id={`${uid}-notice`}>
            {localized(config.privacy.notice, locale, fallback)}{" "}
            <Link href={`/privacy/${config.slug}?lang=${locale}`}>{t.readNotice}</Link>
          </p>
        </div>

        <button className="btn primary big" type="submit" disabled={submitting}>
          {submitting ? t.sending : localized(config.form.submit_label, locale, fallback)}
        </button>
      </form>
    </div>
  );
}

type ControlProps = {
  field: FormFieldDef;
  inputId: string;
  locale: string;
  fallback: string;
  value: string | boolean | undefined;
  error: string | undefined;
  countries: { code: string; name: string }[];
  onChange: (value: string | boolean) => void;
};

function FieldControl({ field, inputId, locale, fallback, value, error, countries, onChange }: ControlProps) {
  const t = ui(locale);
  const text = localized(field.label, locale, fallback);
  const errorId = `${inputId}-error`;
  const aria = { "aria-invalid": error ? true : undefined, "aria-describedby": error ? errorId : undefined };
  const optional = !field.required && field.type !== "checkbox" && <span className="opt">{t.optional}</span>;
  const common = { id: inputId, name: field.id, required: field.required, ...aria };
  const str = typeof value === "string" ? value : "";

  let control: React.ReactNode;
  let labelEl: React.ReactNode = (
    <label htmlFor={inputId}>
      {text}
      {optional}
    </label>
  );

  switch (field.type) {
    case "textarea":
      control = (
        <textarea
          {...common}
          rows={field.role === "free_text" ? 4 : 3}
          maxLength={field.max_length ?? undefined}
          value={str}
          onChange={(e) => onChange(e.target.value)}
        />
      );
      break;
    case "country":
      control = (
        <select {...common} autoComplete="country" value={str} onChange={(e) => onChange(e.target.value)}>
          <option value="">{t.chooseCountry}</option>
          {countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name}
            </option>
          ))}
        </select>
      );
      break;
    case "select":
      if (field.options.length <= PILL_MAX_OPTIONS) {
        const groupId = `${inputId}-label`;
        labelEl = (
          <span className="fl" id={groupId}>
            {text}
            {optional}
          </span>
        );
        control = (
          <div
            className="pills"
            role="radiogroup"
            aria-labelledby={groupId}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            id={inputId}
            tabIndex={-1}
          >
            {field.options.map((o) => (
              <label className="pill" key={o.value}>
                <input
                  type="radio"
                  name={field.id}
                  value={o.value}
                  checked={str === o.value}
                  onChange={() => onChange(o.value)}
                />
                <span>{localized(o.label, locale, fallback)}</span>
              </label>
            ))}
          </div>
        );
      } else {
        control = (
          <select {...common} value={str} onChange={(e) => onChange(e.target.value)}>
            <option value="" />
            {field.options.map((o) => (
              <option key={o.value} value={o.value}>
                {localized(o.label, locale, fallback)}
              </option>
            ))}
          </select>
        );
      }
      break;
    case "checkbox":
      return (
        <div className="field">
          <label className="check" htmlFor={inputId}>
            <input
              {...common}
              type="checkbox"
              checked={value === true}
              onChange={(e) => onChange(e.target.checked)}
            />
            <span>{text}</span>
          </label>
          {error && (
            <p className="field-error" id={errorId}>
              {error}
            </p>
          )}
        </div>
      );
    default:
      control = (
        <input
          {...common}
          type={field.type === "email" ? "email" : field.type === "number" ? "number" : "text"}
          autoComplete={field.role ? AUTOCOMPLETE[field.role] : undefined}
          inputMode={field.type === "email" ? "email" : field.type === "number" ? "decimal" : undefined}
          maxLength={field.max_length ?? undefined}
          value={str}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }

  return (
    <div className="field">
      {labelEl}
      {control}
      {error && (
        <p className="field-error" id={errorId}>
          {error}
        </p>
      )}
    </div>
  );
}
