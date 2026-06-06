import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle, Info, ShieldAlert } from "lucide-react"

const ALERTS = [
  {
    id: "a1",
    severity: "critical",
    message: "Unrecognised person detected at entrance",
    camera: "cam-01",
    time: "09:12",
  },
  {
    id: "a2",
    severity: "warning",
    message: "Motion detected outside business hours",
    camera: "cam-04",
    time: "08:54",
  },
  {
    id: "a3",
    severity: "info",
    message: "Camera 3 went offline",
    camera: "cam-03",
    time: "07:30",
  },
  {
    id: "a4",
    severity: "info",
    message: "Scheduled maintenance window started",
    camera: "—",
    time: "06:00",
  },
]

const ICON = {
  critical: <ShieldAlert className="size-4 text-destructive mt-0.5 shrink-0" />,
  warning: <AlertTriangle className="size-4 text-yellow-500 mt-0.5 shrink-0" />,
  info: <Info className="size-4 text-blue-500 mt-0.5 shrink-0" />,
}

export default function AlertsPage() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Alerts</h1>
        <p className="text-sm text-muted-foreground">Events and incidents requiring attention.</p>
      </div>
      <Card>
        <CardContent className="pt-4">
          <ul className="divide-y divide-border">
            {ALERTS.map((a) => (
              <li key={a.id} className="flex items-start gap-3 py-3">
                {ICON[a.severity as keyof typeof ICON]}
                <div className="flex-1 min-w-0">
                  <p className="text-sm">{a.message}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {a.camera} · {a.time}
                  </p>
                </div>
                <Badge
                  variant={
                    a.severity === "critical"
                      ? "destructive"
                      : a.severity === "warning"
                        ? "outline"
                        : "secondary"
                  }
                  className="shrink-0"
                >
                  {a.severity}
                </Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
