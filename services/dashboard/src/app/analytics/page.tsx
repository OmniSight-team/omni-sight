import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
const FRAME_COUNTS = [40, 80, 55, 120, 95, 140, 60]
const QUERY_COUNTS = [12, 30, 18, 45, 35, 20, 15]

function BarChart({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(...values)
  return (
    <div className="space-y-2">
      <div className="flex items-end gap-1 h-28">
        {values.map((v, i) => (
          <div
            key={i}
            className={`flex-1 rounded-t-sm ${color}`}
            style={{ height: `${(v / max) * 100}%` }}
          />
        ))}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        {DAYS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
    </div>
  )
}

export default function AnalyticsPage() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Analytics</h1>
        <p className="text-sm text-muted-foreground">Indexing throughput and search usage (mock).</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Frames Indexed per Day</CardTitle>
          </CardHeader>
          <CardContent>
            <BarChart values={FRAME_COUNTS} color="bg-primary/70" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Search Queries per Day</CardTitle>
          </CardHeader>
          <CardContent>
            <BarChart values={QUERY_COUNTS} color="bg-chart-2/70" />
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Model Performance</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-6 text-sm md:grid-cols-4">
              <div>
                <dt className="text-muted-foreground">Embed latency</dt>
                <dd className="font-semibold mt-1">~420 ms/frame</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Search latency (p99)</dt>
                <dd className="font-semibold mt-1">~35 ms</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Model</dt>
                <dd className="font-semibold mt-1">SigLIP2 so400m</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Vector dim</dt>
                <dd className="font-semibold mt-1">1152</dd>
              </div>
            </dl>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
