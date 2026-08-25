import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Capstone-IDA",
  description:
    "Benchmarking LLMs on non-coding academic tasks, with reproducible results.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <main>
          <header>
            <h1>
              <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
                Capstone-IDA
              </Link>
            </h1>
          </header>
          {children}
        </main>
      </body>
    </html>
  );
}
