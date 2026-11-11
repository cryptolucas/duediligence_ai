import type { Metadata } from "next";
import Link from "next/link";
import { Inter } from "next/font/google";
import { Plus, Telescope } from "lucide-react";
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
            <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
              <Telescope className="h-5 w-5" aria-hidden />
              Catalejo Deal Desk
            </Link>
            <nav className="flex items-center gap-4 text-xs">
              <Link href="/" className="opacity-80 hover:opacity-100">
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
        {children}
      </body>
    </html>
  );
}
