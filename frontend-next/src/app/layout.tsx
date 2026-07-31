import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Orbitron, Syne, Space_Grotesk, Unbounded } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/design-system/AppShell";
import { QueryProvider } from "@/components/QueryProvider";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" });
const orbitron = Orbitron({ subsets: ["latin"], variable: "--font-orbitron" });
const syne = Syne({ subsets: ["latin"], variable: "--font-syne" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk" });
const unbounded = Unbounded({ subsets: ["latin"], variable: "--font-unbounded" });

export const metadata: Metadata = {
  title: "NOVUS ADOS — Enterprise Decision Operating System",
  description: "Autonomous Defect & Orchestration System for Smart Manufacturing & Supply Chains",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} ${orbitron.variable} ${syne.variable} ${spaceGrotesk.variable} ${unbounded.variable} h-full antialiased dark`}>
      <body className="min-h-full bg-[#070514] text-white">
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}

