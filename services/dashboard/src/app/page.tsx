import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Camera, Layers, Bell, Activity } from "lucide-react"

const STATS = [
  { label: "Cameras Online", value: "4", sub: "All healthy", icon: Camera },
  { label: "Frames Indexed", value: "0", sub: "Awaiting upload", icon: Layers },
  { label: "Alerts Today", value: "2", sub: "1 critical", icon: Bell },
  { label: "System Health", value: "OK", sub: "All services up", icon: Activity },
]

const ACTIVITY = [
  { msg: "Camera 1 — motion detected", time: "09:12" },
  { msg: "Camera 3 — alert triggered", time: "08:54" },
  { msg: "ROI sampler — warmup complete", time: "08:30" },
  { msg: "SigLIP2 model loaded on CPU", time: "08:28" },
]

const SERVICES = [
  { name: "api-server", state: "idle", color: "text-yellow-500" },
  { name: "ai-worker-frame", state: "idle", color: "text-yellow-500" },
  { name: "qdrant (in-memory)", state: "ready", color: "text-green-500" },
  { name: "ingestion", state: "idle", color: "text-yellow-500" },
]

export default function OverviewPage() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-sm text-muted-foreground">Platform status and recent activity.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {STATS.map(({ label, value, sub, icon: Icon }) => (
          <Card key={label}>
            <CardHeader className="pb-0">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-normal text-muted-foreground">
                  {label}
                </CardTitle>
                <Icon className="size-4 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{value}</p>
              <p className="text-xs text-muted-foreground mt-1">{sub}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {ACTIVITY.map(({ msg, time }) => (
                <li key={msg} className="flex justify-between text-sm">
                  <span className="text-foreground">{msg}</span>
                  <span className="text-muted-foreground shrink-0 ml-4">{time}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Services</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {SERVICES.map(({ name, state, color }) => (
                <li key={name} className="flex justify-between text-sm">
                  <span className="font-mono text-xs">{name}</span>
                  <span className={color}>{state}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
