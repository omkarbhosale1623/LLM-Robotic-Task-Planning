import type { Metadata } from "next";

import { Providers } from "@/components/Providers";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "LLM Robotic Task Planner",
  description:
    "Decompose natural-language instructions into validated robot action plans and execute them in a simulated tabletop world.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
