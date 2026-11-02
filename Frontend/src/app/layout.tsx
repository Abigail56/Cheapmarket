import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";

import { Footer } from "@/components/footer";
import { Header } from "@/components/header";
import { SITE_NAME, SITE_TAGLINE } from "@/lib/config";
import { AuthProvider } from "@/providers/auth";
import { CartProvider } from "@/providers/cart";
import { ToastProvider } from "@/providers/toast";

import "./globals.css";

const geist = Geist({ variable: "--font-geist", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: `${SITE_NAME} | Online grocery store`, template: `%s | ${SITE_NAME}` },
  description: `${SITE_TAGLINE}. Rice, beans, oil, vegetables, meat and more.`,
};

export const viewport: Viewport = {
  themeColor: "#0f2d22",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-NG" className={`${geist.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <ToastProvider>
          <AuthProvider>
            <CartProvider>
              <Header />
              <main className="flex-1">{children}</main>
              <Footer />
            </CartProvider>
          </AuthProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
