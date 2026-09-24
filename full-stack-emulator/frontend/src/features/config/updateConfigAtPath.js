export function updateConfigAtPath(config, path, value) {
  const clone = JSON.parse(JSON.stringify(config))
  let cursor = clone
  for (let index = 0; index < path.length - 1; index += 1) {
    cursor = cursor[path[index]]
  }
  cursor[path[path.length - 1]] = value
  return clone
}
