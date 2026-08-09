import { readdir, stat } from 'node:fs/promises'

const assetsDirectory = new URL('../dist/assets/', import.meta.url)
const ENTRY_SCRIPT_BUDGET_BYTES = 525_000
const ENTRY_STYLE_BUDGET_BYTES = 240_000

async function largestMatchingAsset(pattern) {
  const names = (await readdir(assetsDirectory)).filter((name) => pattern.test(name))
  if (!names.length) throw new Error(`没有找到匹配 ${pattern} 的构建产物`)
  const assets = await Promise.all(names.map(async (name) => ({
    name,
    bytes: (await stat(new URL(name, assetsDirectory))).size,
  })))
  return assets.sort((left, right) => right.bytes - left.bytes)[0]
}

function assertWithinBudget(asset, budget, label) {
  const measured = (asset.bytes / 1000).toFixed(2)
  const limit = (budget / 1000).toFixed(2)
  if (asset.bytes > budget) {
    throw new Error(`${label} ${asset.name} 为 ${measured} kB，超过 ${limit} kB 预算`)
  }
  console.log(`${label}: ${asset.name} ${measured} kB / ${limit} kB`)
}

const entryScript = await largestMatchingAsset(/^index-[^.]+\.js$/)
const entryStyle = await largestMatchingAsset(/^index-[^.]+\.css$/)

assertWithinBudget(entryScript, ENTRY_SCRIPT_BUDGET_BYTES, '入口脚本')
assertWithinBudget(entryStyle, ENTRY_STYLE_BUDGET_BYTES, '入口样式')
