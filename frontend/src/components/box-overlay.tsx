import type { SearchBox } from "@/lib/api-client";

// Labelled boxes over a picture or a video (OMNI-X02, D-42). The boxes are fractions of the
// frame, and the overlay is an SVG the size of the frame laid over the element with the same
// fit (`contain` for the player, `cover` for a thumbnail), so the boxes line up with what is
// shown whatever the element's size, letterboxing or cropping. Clicks go through to the element.

export function BoxOverlay({
  boxes,
  width,
  height,
  fit,
  labelSize = 0.04,
  withScore = true,
}: {
  boxes: SearchBox[] | undefined;
  // The frame's own size: the picture's or the video's natural size.
  width: number;
  height: number;
  fit: "contain" | "cover";
  // The label's height as a fraction of the frame's: larger on a small thumbnail.
  labelSize?: number;
  // Off on a thumbnail, where there is no room for it.
  withScore?: boolean;
}) {
  if (!boxes || boxes.length === 0 || width <= 0 || height <= 0) return null;
  const font = height * labelSize;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio={fit === "contain" ? "xMidYMid meet" : "xMidYMid slice"}
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-label={boxes.map((b) => b.label).join(", ")}
    >
      {boxes.map(({ label, score, box: [x1, y1, x2, y2] }, index) => {
        const x = x1 * width;
        const y = y1 * height;
        const text = withScore ? `${label} ${score.toFixed(2)}` : label;
        // Above the box, or inside it when the box touches the top of the frame.
        const textY = y - font * 1.3 >= 0 ? y - font * 1.3 : y;
        return (
          <g key={index}>
            <rect
              x={x}
              y={y}
              width={(x2 - x1) * width}
              height={(y2 - y1) * height}
              fill="none"
              stroke="#facc15"
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
            />
            <rect x={x} y={textY} width={text.length * font * 0.6 + font * 0.6} height={font * 1.3} fill="#facc15" />
            <text x={x + font * 0.3} y={textY + font} fontSize={font} fontFamily="ui-sans-serif, system-ui" fontWeight={600} fill="#18181b">
              {text}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
