const fs = require('node:fs')
const path = require('node:path')
const { app, BrowserWindow } = require('electron')

const [, , sourceArg, outputArg] = process.argv
if (!sourceArg || !outputArg) {
  console.error('Usage: electron render-app-icon.cjs <source.svg> <output.png>')
  process.exit(2)
}

const sourcePath = path.resolve(sourceArg)
const outputPath = path.resolve(outputArg)

app.commandLine.appendSwitch('force-device-scale-factor', '1')

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    width: 1024,
    height: 1024,
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
  const image = await window.webContents.capturePage({ x: 0, y: 0, width: 1024, height: 1024 })
  fs.writeFileSync(outputPath, image.toPNG())
  window.destroy()
  app.quit()
}).catch(error => {
  console.error(error)
  app.exit(1)
})
