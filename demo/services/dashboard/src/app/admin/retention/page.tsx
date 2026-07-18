"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { HardDrive, Save, Pencil, X } from "lucide-react"

type Policy = {
  id: string
  label: string
  domain: string
  duration: string
  storage: string
  status: "active" | "paused"
}

const INITIAL_POLICIES: Policy[] = [
  { id: "p1", label: "Raw footage",       domain: "All",        duration: "30",        storage: "4.2 TB", status: "active" },
  { id: "p2", label: "Indexed frames",    domain: "All",        duration: "90",        storage: "120 GB", status: "active" },
  { id: "p3", label: "Alert clips",       domain: "Security",   duration: "365",       storage: "48 GB",  status: "active" },
  { id: "p4", label: "Forensic dossiers", domain: "All",        duration: "Indefinite",storage: "2 GB",   status: "active" },
  { id: "p5", label: "Safety events",     domain: "Safety",     duration: "180",       storage: "22 GB",  status: "active" },
]

export default function RetentionPage() {
  const [policies, setPolicies] = useState<Policy[]>(INITIAL_POLICIES)
  const [editing, setEditing] = useState<string | null>(null)
  const [draftDuration, setDraftDuration] = useState("")

  function startEdit(p: Policy) {
    setEditing(p.id)
    setDraftDuration(p.duration)
  }

  function saveEdit(id: string) {
    setPolicies((prev) => prev.map((p) => p.id === id ? { ...p, duration: draftDuration } : p))
    setEditing(null)
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Retention Policy</h1>
        <p className="text-sm text-muted-foreground">Configure how long footage and data are kept per domain.</p>
      </div>

      {/* Storage bar */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-2">
          <HardDrive className="size-4 text-muted-foreground" />
          <CardTitle className="text-base">Storage Usage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Used</span>
            <span className="font-medium">4.37 TB / 8 TB</span>
          </div>
          <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
            <div className="h-full bg-primary rounded-full" style={{ width: "54.6%" }} />
          </div>
          <p className="text-xs text-muted-foreground">54.6% used · 3.63 TB free</p>
        </CardContent>
      </Card>

      {/* Policies table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Policies</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left font-medium">Data type</th>
                <th className="px-4 py-3 text-left font-medium">Domain</th>
                <th className="px-4 py-3 text-left font-medium">Retention (days)</th>
                <th className="px-4 py-3 text-left font-medium">Storage</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {policies.map((p) => (
                <tr key={p.id} className="hover:bg-muted/40 transition-colors">
                  <td className="px-4 py-3 font-medium">{p.label}</td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">{p.domain}</td>
                  <td className="px-4 py-3">
                    {editing === p.id ? (
                      <div className="flex items-center gap-2">
                        <Input
                          value={draftDuration}
                          onChange={(e) => setDraftDuration(e.target.value)}
                          className="h-7 w-28 text-xs"
                        />
                        <Button size="icon" variant="ghost" className="size-7" onClick={() => saveEdit(p.id)}>
                          <Save className="size-3.5 text-green-400" />
                        </Button>
                        <Button size="icon" variant="ghost" className="size-7" onClick={() => setEditing(null)}>
                          <X className="size-3.5 text-muted-foreground" />
                        </Button>
                      </div>
                    ) : (
                      <span className="text-muted-foreground font-mono text-xs">
                        {p.duration === "Indefinite" ? "Indefinite" : `${p.duration} days`}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs font-mono">{p.storage}</td>
                  <td className="px-4 py-3">
                    <Badge variant={p.status === "active" ? "secondary" : "outline"}>{p.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {editing !== p.id && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 text-muted-foreground"
                        onClick={() => startEdit(p)}
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground text-center">
        Automated enforcement and purge scheduling is a Phase B feature.
      </p>
    </div>
  )
}
