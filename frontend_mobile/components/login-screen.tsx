"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { API_BASE_URL } from "@/lib/api-config"
import { Bot, Loader2 } from "lucide-react"

interface LoginScreenProps {
  onSuccess: () => void
}

export function LoginScreen({ onSuccess }: LoginScreenProps) {
  const [isRegister, setIsRegister] = useState(false)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [name, setName] = useState("")
  const [role, setRole] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password.trim()) { setError("Please fill in all fields"); return }
    if (isRegister && (!name.trim() || !role.trim())) { setError("Name and role are required"); return }

    setIsLoading(true)
    setError("")

    try {
      const endpoint = isRegister ? `${API_BASE_URL}/api/auth/register` : `${API_BASE_URL}/api/auth/login`
      const body: any = { email: email.trim(), password }
      if (isRegister) {
        body.name = name.trim()
        body.role = role.trim()
        body.description = ""
        body.skills = []
        body.color = "#3B82F6"
      }

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      const data = await res.json()

      if (data.success) {
        if (isRegister) {
          setIsRegister(false)
          setError("")
          setName("")
          setRole("")
          alert("Registration successful! Please log in.")
        } else if (data.access_token) {
          // Use localStorage for persistent login
          localStorage.setItem("auth_token", data.access_token)
          localStorage.setItem("user_info", JSON.stringify(data.user_info))
          onSuccess()
        }
      } else {
        setError(data.message || "Failed")
      }
    } catch {
      setError("Network error. Check if backend is running.")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 safe-top safe-bottom">
      {/* Logo */}
      <div className="mb-8 flex flex-col items-center gap-3">
        <div className="h-16 w-16 rounded-2xl bg-primary/10 flex items-center justify-center">
          <Bot className="h-8 w-8 text-primary" />
        </div>
        <h1 className="text-2xl font-bold">A2A Mobile</h1>
        <p className="text-sm text-muted-foreground text-center">
          Voice-first agent orchestration
        </p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        {error && (
          <div className="text-sm text-red-500 bg-red-500/10 p-3 rounded-lg">{error}</div>
        )}

        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isLoading}
            autoComplete="email"
            className="h-12"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            placeholder="Enter password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={isLoading}
            autoComplete="current-password"
            className="h-12"
          />
        </div>

        {isRegister && (
          <>
            <div className="space-y-2">
              <Label htmlFor="name">Full Name</Label>
              <Input
                id="name"
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={isLoading}
                className="h-12"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role">Role</Label>
              <Input
                id="role"
                placeholder="e.g. Product Manager"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                disabled={isLoading}
                className="h-12"
              />
            </div>
          </>
        )}

        <Button type="submit" className="w-full h-12 text-base" disabled={isLoading}>
          {isLoading ? (
            <><Loader2 className="h-4 w-4 animate-spin mr-2" />{isRegister ? "Registering..." : "Logging in..."}</>
          ) : (
            isRegister ? "Create Account" : "Log In"
          )}
        </Button>

        <Button
          type="button"
          variant="ghost"
          className="w-full text-sm"
          onClick={() => { setIsRegister(!isRegister); setError("") }}
          disabled={isLoading}
        >
          {isRegister ? "Already have an account? Log in" : "Don't have an account? Register"}
        </Button>
      </form>
    </div>
  )
}
