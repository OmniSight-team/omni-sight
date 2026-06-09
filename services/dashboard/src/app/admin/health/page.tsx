import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { CheckCircle2, AlertCircle, XCircle, Cpu, Database, Radio } from "lucide-react"

type ServiceStatus = "healthy" | "idle" | "offline"

type Service = {
  name: string
  status: ServiceStatus
  metric: string
  metricLabel: string
  latency: string
  uptime: string
}

const SERVICES: Service[] = [
  { name: "api-server",         status: "healthy", metric: "12 ms",  metricLabel: "p99 latency",  latency: "12 ms", uptime: "99.9%" },
  { name: "ai-worker-frame",    status: "healthy", metric: "0%",     metricLabel: "GPU load",     latency: "—",     uptime: "99.7%" },
  { name: "ingestion",          status: "idle",    metric: "0",      metricLabel: "queue depth",  latency: "—",     uptime: "100%"  },
  { name: "query-service",      status: "healthy", metric: "8 ms",   metricLabel: "p99 latency",  latency: "8 ms",  uptime: "99.8%" },
  { name: "qdrant (in-memory)", status: "healthy", metric: "4 ms",   metricLabel: "vector query", latency: "4 ms",  uptime: "100%"  },
  { name: "postgresql",         status: "healthy", metric: "2 ms",   metricLabel: "query latency",latency: "2 ms",  uptime: "100%"  },
  { name: "rabbitmq",           status: "offline", metric: "—",      metricLabel: "queue depth",  latency: "—",     uptime: "0%"    },
]

const STATUS_ICON: Record<ServiceStatus, React.ReactNode> = {
  healthy: <CheckCircle2 className="size-4 text-green-400 shrink-0" />,
  idle:    <AlertCircle  className="size-4 text-yellow-400 shrink-0" />,
  offline: <XCircle      className="size-4 text-destructive shrink-0" />,
}

const STATUS_BADGE: Record<ServiceStatus, "default" | "secondary" | "destructive"> = {
  healthy: "default",
  idle:    "secondary",
  offline: "destructive",
}

const counts = {
  healthy: SERVICES.filter((s) => s.status === "healthy").length,
  idle:    SERVICES.filter((s) => s.status === "idle").length,
  offline: SERVICES.filter((s) => s.status === "offline").length,
}

export default function SystemHealthPage() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">System Health</h1>
        <p className="text-sm text-muted-foreground">
          Real-time status for each service in the deployment.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <CardContent className="pt-4 pb-3 flex items-center gap-3">
            <CheckCircle2 className="size-7 text-green-400 shrink-0" />
            <div>
              <p className="text-2xl font-semibold leading-none">{counts.healthy}</p>
              <p className="text-xs text-muted-foreground mt-1">Healthy</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3 flex items-center gap-3">
            <AlertCircle className="size-7 text-yellow-400 shrink-0" />
            <div>
              <p className="text-2xl font-semibold leading-none">{counts.idle}</p>
              <p className="text-xs text-muted-foreground mt-1">Idle</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3 flex items-center gap-3">
            <XCircle className="size-7 text-destructive shrink-0" />
            <div>
              <p className="text-2xl font-semibold leading-none">{counts.offline}</p>
              <p className="text-xs text-muted-foreground mt-1">Offline</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Service table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Services</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left font-medium">Service</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Metric</th>
                <th className="px-4 py-3 text-left font-medium">Latency</th>
                <th className="px-4 py-3 text-left font-medium">Uptime</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {SERVICES.map((s) => (
                <tr key={s.name} className="hover:bg-muted/40 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {STATUS_ICON[s.status]}
                      <span className="font-mono text-xs">{s.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={STATUS_BADGE[s.status]}>{s.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    <span className="font-mono text-foreground">{s.metric}</span>
                    <span className="ml-1">({s.metricLabel})</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground font-mono">{s.latency}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground font-mono">{s.uptime}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Architecture icons */}
      <div className="flex items-center gap-6 text-xs text-muted-foreground justify-center pt-2">
        <span className="flex items-center gap-1.5"><Radio className="size-3.5" /> Ingestion layer</span>
        <span className="flex items-center gap-1.5"><Cpu className="size-3.5" /> AI Workers</span>
        <span className="flex items-center gap-1.5"><Database className="size-3.5" /> Vector + SQL stores</span>
      </div>
    </div>
  )
}
