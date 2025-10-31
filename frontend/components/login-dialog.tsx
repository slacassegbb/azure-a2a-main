"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { User } from "lucide-react"

interface LoginDialogProps {
  onLogin?: (username: string, password: string) => void
}

interface LoginResponse {
  success: boolean
  access_token?: string
  user_info?: {
    user_id: string
    email: string
    name: string
    role: string
    description: string
    skills: string[]
    color: string
  }
  message?: string
}

interface RegisterRequest {
  email: string
  password: string
  name: string
  role: string
  description: string
  skills: string[]
  color: string
}

export function LoginDialog({ onLogin }: LoginDialogProps) {
  const [isRegisterMode, setIsRegisterMode] = useState(false)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [name, setName] = useState("")
  const [role, setRole] = useState("")
  const [description, setDescription] = useState("")
  const [skills, setSkills] = useState("")
  const [color, setColor] = useState("#3B82F6")
  const [isOpen, setIsOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")

  const resetForm = () => {
    setEmail("")
    setPassword("")
    setName("")
    setRole("")
    setDescription("")
    setSkills("")
    setColor("#3B82F6")
    setError("")
  }

  const toggleMode = () => {
    setIsRegisterMode(!isRegisterMode)
    resetForm()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (!email.trim() || !password.trim()) {
      setError("Please fill in all fields")
      return
    }

    if (isRegisterMode && (!name.trim() || !role.trim())) {
      setError("Please fill in all required fields")
      return
    }

    setIsLoading(true)
    setError("")

    try {
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || "http://localhost:12000"
      let endpoint = `${baseUrl}/api/auth/login`
      let requestBody: any = {
        email: email.trim(),
        password: password,
      }

      if (isRegisterMode) {
        endpoint = `${baseUrl}/api/auth/register`
        requestBody = {
          email: email.trim(),
          password: password,
          name: name.trim(),
          role: role.trim(),
          description: description.trim(),
          skills: skills.split(',').map(skill => skill.trim()).filter(skill => skill.length > 0),
          color: color
        }
      }

      // Make request to backend
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      })

      const data: LoginResponse = await response.json()

      if (data.success) {
        if (isRegisterMode) {
          // Switch to login mode after successful registration
          setIsRegisterMode(false)
          resetForm()
          setError("")
          alert("Registration successful! Please log in.")
        } else {
          // Handle login success
          if (data.access_token) {
            // Store token in sessionStorage (clears on browser/tab close)
            sessionStorage.setItem("auth_token", data.access_token)
            sessionStorage.setItem("user_info", JSON.stringify(data.user_info))

            // Call onLogin callback if provided
            onLogin?.(email, password)

            // Clear form and close dialog
            resetForm()
            setIsOpen(false)

            // Reload page to reconnect WebSocket with authentication
            window.location.reload()
          }
        }
      } else {
        setError(data.message || `${isRegisterMode ? 'Registration' : 'Login'} failed`)
      }
    } catch (err) {
      console.error(`${isRegisterMode ? 'Registration' : 'Login'} error:`, err)
      setError("Network error. Please check if the backend is running.")
    } finally {
      setIsLoading(false)
    }
  }

  const handleClose = () => {
    // Reset form when dialog is closed
    resetForm()
    setIsRegisterMode(false)
    setIsOpen(false)
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => {
      if (!open) {
        handleClose()
      } else {
        setIsOpen(open)
      }
    }}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="h-9 w-9">
          <User size={20} />
          <span className="sr-only">Login</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[500px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isRegisterMode ? "Register" : "Login"}</DialogTitle>
          <DialogDescription>
            {isRegisterMode ? (
              "Create a new account to join the conversation."
            ) : (
              <>
                Enter your credentials to access your account.
                <br />
                <small className="text-muted-foreground">
                  Try: simon@example.com / simon123
                </small>
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 py-4">
            {error && (
              <div className="text-sm text-red-500 bg-red-50 p-2 rounded">
                {error}
              </div>
            )}
            
            {/* Email Field */}
            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="Enter your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isLoading}
                required
              />
            </div>
            
            {/* Password Field */}
            <div className="grid gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                required
              />
            </div>

            {/* Registration-specific fields */}
            {isRegisterMode && (
              <>
                <div className="grid gap-2">
                  <Label htmlFor="name">Full Name</Label>
                  <Input
                    id="name"
                    type="text"
                    placeholder="Enter your full name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    disabled={isLoading}
                    required
                  />
                </div>
                
                <div className="grid gap-2">
                  <Label htmlFor="role">Role</Label>
                  <Input
                    id="role"
                    type="text"
                    placeholder="e.g. Software Developer, Product Manager"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    disabled={isLoading}
                    required
                  />
                </div>
                
                <div className="grid gap-2">
                  <Label htmlFor="description">Description</Label>
                  <Textarea
                    id="description"
                    placeholder="Brief description of your background and expertise"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    disabled={isLoading}
                    rows={3}
                  />
                </div>
                
                <div className="grid gap-2">
                  <Label htmlFor="skills">Skills (comma-separated)</Label>
                  <Input
                    id="skills"
                    type="text"
                    placeholder="e.g. JavaScript, Python, React, Node.js"
                    value={skills}
                    onChange={(e) => setSkills(e.target.value)}
                    disabled={isLoading}
                  />
                </div>
                
                <div className="grid gap-2">
                  <Label htmlFor="color">Avatar Color</Label>
                  <div className="flex gap-2 items-center">
                    <Input
                      id="color"
                      type="color"
                      value={color}
                      onChange={(e) => setColor(e.target.value)}
                      disabled={isLoading}
                      className="w-16 h-10"
                    />
                    <span className="text-sm text-muted-foreground">Choose your avatar color</span>
                  </div>
                </div>
              </>
            )}
          </div>
          
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={handleClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button 
              type="button" 
              variant="ghost" 
              onClick={toggleMode} 
              disabled={isLoading}
              className="text-primary"
            >
              {isRegisterMode ? "Switch to Login" : "Create Account"}
            </Button>
            <Button type="submit" disabled={!email.trim() || !password.trim() || isLoading}>
              {isLoading ? 
                (isRegisterMode ? "Registering..." : "Logging in...") : 
                (isRegisterMode ? "Register" : "Login")
              }
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
