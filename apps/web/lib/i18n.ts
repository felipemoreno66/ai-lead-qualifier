export const SUPPORTED_UI_LOCALES = ["en", "es"] as const;
export type UiLocale = (typeof SUPPORTED_UI_LOCALES)[number];

type Strings = {
  language: string;
  applyTitle: (name: string) => string;
  applyLead: string;
  stepOf: (n: number, total: number) => string;
  optional: string;
  chooseCountry: string;
  consentLabel: string;
  readNotice: string;
  sending: string;
  fixFields: string;
  required: string;
  invalid: string;
  tooLong: (n: number) => string;
  tooManyLinks: string;
  networkError: string;
  rateLimited: string;
  consentOutdated: string;
  genericError: string;
  thanksTitle: string;
  thanksBody: string;
  reference: string;
  privacyTitle: string;
  controller: string;
  retentionLabel: string;
  retention: (days: number) => string;
  version: string;
  backToForm: string;
};

const en: Strings = {
  language: "Language",
  applyTitle: (name) => `Apply to ${name}`,
  applyLead: "A real person reads every application. Tell us a little about you and what you are looking for.",
  stepOf: (n, total) => `${n} of ${total}`,
  optional: "optional",
  chooseCountry: "Choose your country",
  consentLabel: "I have read the privacy notice and agree to the use of my data as described.",
  readNotice: "Read the full privacy notice",
  sending: "Sending",
  fixFields: "Please check these fields",
  required: "This field is required.",
  invalid: "Check this answer.",
  tooLong: (n) => `Use at most ${n} characters.`,
  tooManyLinks: "Use at most 3 links.",
  networkError: "We could not reach the server. Check your connection and try again.",
  rateLimited: "Too many attempts. Please wait a few minutes and try again.",
  consentOutdated: "The privacy notice changed. Reload this page, read it again and resubmit.",
  genericError: "Something went wrong on our side. Please try again in a moment.",
  thanksTitle: "Application received",
  thanksBody: "A person will read it and write back. You do not need to do anything else.",
  reference: "Your reference",
  privacyTitle: "Privacy notice",
  controller: "Data controller",
  retentionLabel: "Retention",
  retention: (days) => `Applications are kept for ${days} days.`,
  version: "Version",
  backToForm: "Back to the application form",
};

const es: Strings = {
  language: "Idioma",
  applyTitle: (name) => `Postula a ${name}`,
  applyLead: "Una persona real lee cada solicitud. Cuéntanos un poco sobre ti y lo que buscas.",
  stepOf: (n, total) => `${n} de ${total}`,
  optional: "opcional",
  chooseCountry: "Elige tu país",
  consentLabel: "He leído el aviso de privacidad y acepto el uso de mis datos como se describe.",
  readNotice: "Leer el aviso de privacidad completo",
  sending: "Enviando",
  fixFields: "Revisa estos campos",
  required: "Este campo es obligatorio.",
  invalid: "Revisa esta respuesta.",
  tooLong: (n) => `Usa como máximo ${n} caracteres.`,
  tooManyLinks: "Usa como máximo 3 enlaces.",
  networkError: "No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.",
  rateLimited: "Demasiados intentos. Espera unos minutos e inténtalo de nuevo.",
  consentOutdated: "El aviso de privacidad cambió. Recarga la página, léelo de nuevo y envía otra vez.",
  genericError: "Algo salió mal de nuestro lado. Inténtalo de nuevo en un momento.",
  thanksTitle: "Solicitud recibida",
  thanksBody: "Una persona la leerá y te responderá. No necesitas hacer nada más.",
  reference: "Tu referencia",
  privacyTitle: "Aviso de privacidad",
  controller: "Responsable de los datos",
  retentionLabel: "Conservación",
  retention: (days) => `Las solicitudes se conservan ${days} días.`,
  version: "Versión",
  backToForm: "Volver al formulario",
};

const DICTIONARY: Record<UiLocale, Strings> = { en, es };

export function ui(locale: string): Strings {
  return DICTIONARY[(SUPPORTED_UI_LOCALES as readonly string[]).includes(locale) ? (locale as UiLocale) : "en"];
}

/** Pick a language the workspace supports: requested, else the workspace default. */
export function pickLocale(requested: string | undefined, supported: string[], fallback: string): string {
  return requested && supported.includes(requested) ? requested : fallback;
}

/** Localized text with fallback to the default language, then to any value. */
export function localized(text: Record<string, string> | null | undefined, locale: string, fallback: string): string {
  if (!text) return "";
  return text[locale] ?? text[fallback] ?? Object.values(text)[0] ?? "";
}
