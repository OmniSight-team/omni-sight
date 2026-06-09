import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Bell, Layers, Activity, ShieldAlert, AlertTriangle, Info } from "lucide-react"
import Image from "next/image"
import Link from "next/link"

const CAMERAS = [
  { id: "cam-01", name: "Entrance",    status: "online",  img: "/cameras/cam1.jpg" },
  { id: "cam-02", name: "Parking Lot", status: "online",  img: "/cameras/cam2.jpg" },
  { id: "cam-03", name: "Warehouse A", status: "offline", img: "/cameras/cam3.jpg" },
  { id: "cam-04", name: "Loading Bay", status: "online",  img: "/cameras/cam4.jpg" },
]

const ALERTS = [
  { id: "a1", severity: "critical", message: "Unattended object at entrance",   camera: "cam-01", time: "09:12", domain: "Security" },
  { id: "a2", severity: "critical", message: "Emergency exit blocked",           camera: "cam-02", time: "09:05", domain: "Safety" },
  { id: "a3", severity: "warning",  message: "Vehicle in restricted zone",       camera: "cam-04", time: "08:54", domain: "Operations" },
  { id: "a4", severity: "warning",  message: "Motion outside business hours",    camera: "cam-04", time: "08:42", domain: "Security" },
  { id: "a5", severity: "info",     message: "Camera 3 went offline",            camera: "cam-03", time: "07:30", domain: "Operations" },
]

const SEVERITY_ICON = {
  critical: <ShieldAlert   className="size-3.5 text-destructive mt-0.5 shrink-0" />,
  warning:  <AlertTriangle className="size-3.5 text-yellow-500 mt-0.5 shrink-0" />,
  info:     <Info          className="size-3.5 text-blue-400 mt-0.5 shrink-0" />,
}

export default function DashboardPage() {
  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Live feeds, active alerts, and system status.</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <CardContent className="pt-4 pb-3 flex items-center gap-3">
            <Activity className="size-7 text-green-400 shrink-0" />
            <div>
              <p className="text-2xl font-semibold leading-none">
                3<span className="text-muted-foreground text-base font-normal"> / 4</span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">Cameras online</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3 flex items-center gap-3">
            <Bell className="size-7 text-yellow-400 shrink-0" />
            <div>
              <p className="text-2xl font-semibold leading-none">4</p>
              <p className="text-xs text-muted-foreground mt-1">Alerts today</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3 flex items-center gap-3">
            <Layers className="size-7 text-primary shrink-0" />
            <div>
              <p className="text-2xl font-semibold leading-none">—</p>
              <p className="text-xs text-muted-foreground mt-1">Clips indexed</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Two-column: feeds left, alerts right */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_280px]">
        {/* Camera grid */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2 pt-3 px-4">
            <CardTitle className="text-sm font-medium">Live Feeds</CardTitle>
            <Link href="/admin/cameras" className="text-xs text-primary hover:underline">
              Configure →
            </Link>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="grid grid-cols-2 gap-3">
              {CAMERAS.map((cam) => (
                <div key={cam.id} className="space-y-1.5">
                  <div className="relative rounded-lg overflow-hidden aspect-video bg-muted border border-border">
                    {cam.status === "online" ? (
                      <Image src={cam.img} alt={cam.name} fill className="object-cover" />
                    ) : (
                      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
                        <div className="size-2 rounded-full bg-destructive/60" />
                        <p className="text-[10px] text-muted-foreground">Offline</p>
                      </div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent pointer-events-none" />
                    <div className="absolute bottom-1.5 left-2 text-[10px] text-white/90 font-mono drop-shadow">
                      {cam.id.toUpperCase()}
                    </div>
                    <div className="absolute top-1.5 right-1.5">
                      <Badge
                        variant={cam.status === "online" ? "default" : "destructive"}
                        className="text-[9px] px-1.5 py-0 h-4 font-mono"
                      >
                        {cam.status === "online" ? "● LIVE" : "● OFF"}
                      </Badge>
                    </div>
                  </div>
                  <p className="text-[11px] text-muted-foreground">{cam.name}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Alerts panel */}
        <Card className="flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-2 pt-3 px-4 shrink-0">
            <CardTitle className="text-sm font-medium">Recent Alerts</CardTitle>
            <Link href="/alerts" className="text-xs text-primary hover:underline">
              View all →
            </Link>
          </CardHeader>
          <CardContent className="px-0 pb-0 flex-1">
            <ul className="divide-y divide-border">
              {ALERTS.map((a) => (
                <li key={a.id} className="flex items-start gap-2.5 px-4 py-3">
                  {SEVERITY_ICON[a.severity as keyof typeof SEVERITY_ICON]}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium leading-snug">{a.message}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {a.camera} · {a.time} · {a.domain}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
