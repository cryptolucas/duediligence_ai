import type { Metadata } from "next";
import Link from "next/link";
import { Inter } from "next/font/google";
import { Plus, Telescope } from "lucide-react";
import { AppGate } from "@/components/app-gate";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Catalejo Deal Desk",
  description: "Screening financiero y due diligence preliminar para Private Equity en Colombia y Latinoamérica.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={inter.variable}>
      <body className="min-h-screen font-sans">
        <header className="sticky top-0 z-40 h-12 border-b bg-primary text-primary-foreground">
          <div className="flex h-full items-center justify-between px-4">
            <Link href="/" className="flex min-w-0 items-center gap-2 whitespace-nowrap text-sm font-semibold tracking-tight">
              <Telescope className="h-5 w-5 shrink-0" aria-hidden />
              Catalejo Deal Desk
            </Link>
            <nav className="flex shrink-0 items-center gap-4 whitespace-nowrap text-xs">
              <Link href="/" className="hidden opacity-80 hover:opacity-100 sm:inline">
                Operaciones
              </Link>
              <Link
                href="/deals/new"
                className="inline-flex items-center gap-1 rounded-md bg-white/10 px-2.5 py-1.5 font-medium hover:bg-white/20"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden /> Nueva operación
              </Link>
            </nav>
          </div>
        </header>
        <AppGate>{children}</AppGate>
      </body>
    </html>
  );
}
