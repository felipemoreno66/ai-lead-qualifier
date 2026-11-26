import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { PublicDemoBanner } from "@/components/public-demo-banner";
import { Providers } from "./providers";

const youngSerif = localFont({
  src: [{ path: "./fonts/young-serif-latin-400-normal.woff2", weight: "400", style: "normal" }],
  variable: "--font-serif",
  display: "swap",
});

const figtree = localFont({
  src: [
    { path: "./fonts/figtree-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/figtree-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "./fonts/figtree-latin-600-normal.woff2", weight: "600", style: "normal" },
    { path: "./fonts/figtree-latin-700-normal.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-ui",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "AI Lead Qualifier", template: "%s · AI Lead Qualifier" },
  description:
    "Open-source mini CRM that scores inbound leads against your own criteria. A person approves every reply.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${youngSerif.variable} ${figtree.variable}`}>
      <body>
        <PublicDemoBanner />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
