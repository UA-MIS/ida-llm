import type { Metadata } from "next";
import { FacultyHome } from "@/components/faculty-home";
import { FacultyShell } from "@/components/faculty-shell";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "AI benchmark results — Capstone-IDA",
  description: "Compare tested AI performance by major and explore results for general business classes.",
};

export default function HomePage() {
  return <FacultyShell><FacultyHome /></FacultyShell>;
}
