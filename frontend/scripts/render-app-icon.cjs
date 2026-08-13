const fs = require('node:fs')
const path = require('node:path')
const { app, BrowserWindow } = require('electron')

const [, , sourceArg, outputArg, sizeArg = '1024'] = process.argv
if (!sourceArg || !outputArg) {
  console.error('Usage: electron render-app-icon.cjs <source.svg> <output.png> [logical-size]')
  process.exit(2)
}

const sourcePath = path.resolve(sourceArg)
const outputPath = path.resolve(outputArg)
const logicalSize = Number.parseInt(sizeArg, 10)
if (!Number.isInteger(logicalSize) || logicalSize < 1 || logicalSize > 2048) {
  console.error(`Invalid logical size: ${sizeArg}`)
  process.exit(2)
}

app.commandLine.appendSwitch('force-device-scale-factor', '1')

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    width: logicalSize,
    height: logicalSize,
    useContentSize: true,
    show: false,
    transparent: true,
    backgroundColor: '#00000000',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  await window.loadFile(sourcePath)
  const image = await window.webContents.capturePage({
    x: 0,
    y: 0,
    width: logicalSize,
    height: logicalSize,
  })
  fs.writeFileSync(outputPath, image.toPNG())
  window.destroy()
  app.quit()
}).catch(error => {
  console.error(error)
  app.exit(1)
})
