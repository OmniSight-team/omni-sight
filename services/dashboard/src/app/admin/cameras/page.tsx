"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Video, Plus, Settings2, X } from "lucide-react"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import Image from "next/image"

type Domain = "Security" | "Safety" | "Operations"

type Camera = {
  id: string
  name: string
  location: string
  domain: Domain
  status: "online" | "offline"
  fps: number
  res: string
  img: string
}

const INITIAL_CAMERAS: Camera[] = [
  { id: "cam-01", name: "Entrance",    location: "North gate",    domain: "Security",   status: "online",  fps: 30, res: "1920×1080", img: "/cameras/cam1.jpg" },
  { id: "cam-02", name: "Parking Lot", location: "West perimeter",domain: "Security",   status: "online",  fps: 25, res: "1280×720",  img: "/cameras/cam2.jpg" },
  { id: "cam-03", name: "Warehouse A", location: "Building 3",    domain: "Operations", status: "offline", fps: 0,  res: "1920×1080", img: "/cameras/cam3.jpg" },
  { id: "cam-04", name: "Loading Bay", location: "South dock",    domain: "Operations", status: "online",  fps: 30, res: "1920×1080", img: "/cameras/cam4.jpg" },
]

const DOMAIN_COLOR: Record<Domain, string> = {
  Security:   "text-red-400",
  Safety:     "text-yellow-400",
  Operations: "text-blue-400",
}

export default function CameraConfigPage() {
  const [cameras, setCameras] = useState<Camera[]>(INITIAL_CAMERAS)
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState({ name: "", location: "", domain: "Security" as Domain, url: "" })

  function handleAdd() {
    if (!form.name.trim()) return
    const id = `cam-0${cameras.length + 1}`
    setCameras((prev) => [
      ...prev,
      { id, name: form.name, location: form.location, domain: form.domain, status: "offline", fps: 0, res: "—", img: "" },
    ])
    setForm({ name: "", location: "", domain: "Security", url: "" })
    setAddOpen(false)
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Camera Configuration</h1>
          <p className="text-sm text-muted-foreground">Register cameras and configure stream settings.</p>
        </div>
        <Button size="sm" className="gap-1.5" onClick={() => setAddOpen(true)}>
          <Plus className="size-4" />
          Add Camera
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {cameras.map((cam) => (
          <Card key={cam.id}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Video className="size-4" />
                  {cam.name}
                </CardTitle>
                <Badge variant={cam.status === "online" ? "default" : "destructive"}>
                  {cam.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="relative rounded-lg overflow-hidden aspect-video bg-muted border border-border">
                {cam.status === "online" && cam.img ? (
                  <Image src={cam.img} alt={`${cam.name} feed`} fill className="object-cover" />
                ) : (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
                    <div className="size-2 rounded-full bg-destructive/60" />
                    <p className="text-xs text-muted-foreground">Offline</p>
                  </div>
                )}
              </div>
              <div className="flex items-center justify-between">
                <div className="text-xs text-muted-foreground space-y-0.5">
                  <div className="flex items-center gap-3">
                    <span className="font-mono">{cam.id.toUpperCase()}</span>
                    <span>{cam.res}</span>
                    {cam.fps > 0 && <span>{cam.fps} fps</span>}
                  </div>
                  <div className="flex items-center gap-1">
                    <span>{cam.location}</span>
                    <span>·</span>
                    <span className={DOMAIN_COLOR[cam.domain]}>{cam.domain}</span>
                  </div>
                </div>
                <Button variant="ghost" size="icon" className="size-7 shrink-0 text-muted-foreground">
                  <Settings2 className="size-3.5" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Add camera dialog */}
      <Dialog open={addOpen} onOpenChange={(o) => setAddOpen(o)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Add Camera</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Name</label>
              <Input
                placeholder="Entrance Gate"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Location</label>
              <Input
                placeholder="North wing, floor 2"
                value={form.location}
                onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Domain</label>
              <select
                value={form.domain}
                onChange={(e) => setForm((f) => ({ ...f, domain: e.target.value as Domain }))}
                className="w-full text-sm bg-muted border border-border rounded-md px-3 py-2 text-foreground outline-none focus:ring-1 focus:ring-ring"
              >
                <option>Security</option>
                <option>Safety</option>
                <option>Operations</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Stream URL</label>
              <Input
                placeholder="rtsp://192.168.1.x:554/stream"
                value={form.url}
                onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setAddOpen(false)}>
              <X className="size-3.5 mr-1.5" /> Cancel
            </Button>
            <Button size="sm" onClick={handleAdd} disabled={!form.name.trim()}>
              <Plus className="size-3.5 mr-1.5" /> Add Camera
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
