import type { Metadata } from "next";
import { Unbounded, Space_Grotesk } from "next/font/google";

const unbounded = Unbounded({
  subsets: ["latin"],
  variable: "--font-studio-display",
  weight: ["500", "700", "900"],
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-studio-body",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Novus Studio — Applied Intelligence for the Plant Floor",
  description:
    "Novus Studio is the applied-AI arm behind ADOS: an autonomous system that senses, reasons about cause, and acts inside limits it never has to be told twice.",
};

export default function NovusStudioLayout({ children }: { children: React.ReactNode }) {
  return <div className={`${unbounded.variable} ${spaceGrotesk.variable}`}>{children}</div>;
}
