import type { Metadata } from 'next';
import { config } from '@/lib/env';
import './globals.css';

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: config.boardTitle,
    description: `Sprint and story board for ${config.teamLabel}`,
  };
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // The accent is configurable per deployment; it is validated as a hex colour
  // in config before it reaches the stylesheet.
  const accent = config.boardAccent;
  return (
    <html lang="en">
      <head>
        <style
          dangerouslySetInnerHTML={{
            __html: `:root{--accent:${accent};--accent-hover:color-mix(in srgb,${accent} 86%,#000);--accent-active:color-mix(in srgb,${accent} 74%,#000);--accent-ring:color-mix(in srgb,${accent} 32%,transparent);--accent-wash:color-mix(in srgb,${accent} 8%,transparent);}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
