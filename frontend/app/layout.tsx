import type React from "react"
import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import { cn } from "@/lib/utils"
import { ThemeProvider } from "@/components/theme-provider"
import { EventHubProvider } from "@/contexts/event-hub-context"

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" })

export const metadata: Metadata = {
  title: "A2A Multi-Agent Host Orchestrator",
  description: "A comprehensive AI chat interface demo.",
    generator: 'v0.dev'
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={cn("min-h-screen bg-background font-sans antialiased", inter.variable)}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <EventHubProvider>
            {/* The wrapper around children has been removed to allow full-width content. */}
            {children}
          </EventHubProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
