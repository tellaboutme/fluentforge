import type { Metadata, Viewport } from "next";

import { OfflineNotice, ServiceWorkerRegistration } from "@/components/Offline";
import { SessionProvider } from "@/lib/session";

import "./globals.css";

export const metadata: Metadata = {
  title: "FluentForge",
  description: "Adaptive English learning from A1 to C2",
  manifest: "/manifest.webmanifest",
  applicationName: "FluentForge",
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
};

export const viewport: Viewport = {
  themeColor: "#0f1419",
  // Zooming is how a low-vision learner reads. Locking it is an
  // accessibility failure that costs nothing to avoid.
  maximumScale: 5,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        {/* Above the content, because a learner needs to know the state of
            the connection before they start writing something that cannot be
            checked until it comes back. */}
        <OfflineNotice />
        <SessionProvider>{children}</SessionProvider>
        <ServiceWorkerRegistration />
      </body>
    </html>
  );
}
