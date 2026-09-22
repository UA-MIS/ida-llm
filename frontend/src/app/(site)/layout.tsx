import { FacultyShell } from "@/components/faculty-shell";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return <FacultyShell>{children}</FacultyShell>;
}
