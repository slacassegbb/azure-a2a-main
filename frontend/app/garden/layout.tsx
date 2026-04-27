import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Smart Garden Dashboard",
  description: "AI-powered autonomous garden monitoring and control",
};

export default function GardenLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="dark" style={{ background: "hsl(220, 20%, 7%)", minHeight: "100vh" }}>
      {children}
    </div>
  );
}
