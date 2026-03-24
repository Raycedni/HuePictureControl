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
