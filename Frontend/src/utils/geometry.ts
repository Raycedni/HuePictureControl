/**
 * Normalize pixel coordinates to [0..1] range.
 */
export function normalize(
  points: [number, number][],
  width: number,
  height: number,
): [number, number][] {
  return points.map(([x, y]) => [x / width, y / height])
}

/**
 * Denormalize [0..1] coordinates to pixel coordinates.
 */
export function denormalize(
  points: [number, number][],
  width: number,
  height: number,
): [number, number][] {
  return points.map(([x, y]) => [x * width, y * height])
}

/**
 * Compute the area of a polygon using the shoelace formula.
 */
export function polygonArea(points: [number, number][]): number {
  const n = points.length
  if (n < 3) return 0
  let area = 0
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    area += points[i][0] * points[j][1]
    area -= points[j][0] * points[i][1]
  }
  return Math.abs(area) / 2
}

/**
 * Ray-casting algorithm to determine if a point is inside a polygon.
 */
export function pointInPolygon(
  point: [number, number],
  polygon: [number, number][],
): boolean {
  const [px, py] = point
  let inside = false
  const n = polygon.length

  for (let i = 0, j = n - 1; i < n; j = i++) {
    const [xi, yi] = polygon[i]
    const [xj, yj] = polygon[j]

    const intersects =
      yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi

    if (intersects) {
      inside = !inside
    }
  }

  return inside
}
