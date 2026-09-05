const TILES = [
  { title: "Alerts needing attention", note: "Filled in when alerting ships" },
  { title: "Camera health", note: "Filled in when camera ingestion ships" },
  { title: "Activity", note: "Filled in when the activity feed ships" },
  { title: "Recent reports", note: "Filled in when incident reporting ships" },
  { title: "Storage", note: "Filled in when storage monitoring ships" },
];

export default function DashboardPage() {
  return (
    <main className="p-6">
      <h1 className="mb-4 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
        Operations Dashboard
      </h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {TILES.map((tile) => (
          <div
            key={tile.title}
            className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
          >
            <h2 className="font-medium text-zinc-900 dark:text-zinc-50">{tile.title}</h2>
            <p className="mt-8 text-sm text-zinc-400 dark:text-zinc-600">{tile.note}</p>
          </div>
        ))}
      </div>
    </main>
  );
}
