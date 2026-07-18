"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Plus, MoreHorizontal, UserCheck, UserX } from "lucide-react"

type Role = "Admin" | "Operator" | "Analyst"
type UserStatus = "active" | "inactive"

type User = {
  id: string
  name: string
  email: string
  role: Role
  status: UserStatus
  lastSeen: string
}

const INITIAL_USERS: User[] = [
  { id: "u1", name: "Ahmad Tawil",  email: "admin@omni.local",    role: "Admin",    status: "active",   lastSeen: "Just now" },
  { id: "u2", name: "Sara Malik",   email: "operator@omni.local", role: "Operator", status: "active",   lastSeen: "2 h ago" },
  { id: "u3", name: "James Porter", email: "james@omnisight.io",  role: "Analyst",  status: "active",   lastSeen: "Yesterday" },
  { id: "u4", name: "Lena Hofer",   email: "lena@omnisight.io",   role: "Operator", status: "inactive", lastSeen: "3 d ago" },
]

const ROLE_VARIANT: Record<Role, "default" | "secondary" | "outline"> = {
  Admin:    "default",
  Operator: "secondary",
  Analyst:  "outline",
}

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>(INITIAL_USERS)

  function toggleStatus(id: string) {
    setUsers((prev) =>
      prev.map((u) => u.id === id ? { ...u, status: u.status === "active" ? "inactive" : "active" } : u)
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Users &amp; Roles</h1>
          <p className="text-sm text-muted-foreground">Manage accounts and role-based permissions.</p>
        </div>
        <Button size="sm" className="gap-1.5">
          <Plus className="size-4" />
          Add User
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Accounts</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left font-medium">Name</th>
                <th className="px-4 py-3 text-left font-medium">Email</th>
                <th className="px-4 py-3 text-left font-medium">Role</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Last seen</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-muted/40 transition-colors">
                  <td className="px-4 py-3 font-medium">{u.name}</td>
                  <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{u.email}</td>
                  <td className="px-4 py-3">
                    <Badge variant={ROLE_VARIANT[u.role]}>{u.role}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`flex items-center gap-1.5 text-xs ${u.status === "active" ? "text-green-400" : "text-muted-foreground"}`}>
                      <span className={`size-1.5 rounded-full ${u.status === "active" ? "bg-green-400" : "bg-muted-foreground"}`} />
                      {u.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">{u.lastSeen}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 text-muted-foreground"
                        title={u.status === "active" ? "Deactivate" : "Activate"}
                        onClick={() => toggleStatus(u.id)}
                      >
                        {u.status === "active" ? <UserX className="size-3.5" /> : <UserCheck className="size-3.5" />}
                      </Button>
                      <Button variant="ghost" size="icon" className="size-7 text-muted-foreground">
                        <MoreHorizontal className="size-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground text-center">
        Full user management with invitations (FR-10) is a Phase B feature.
      </p>
    </div>
  )
}
