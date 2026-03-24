import { useState } from 'react'
import './App.css'
import PairingFlow from './components/PairingFlow'
import PreviewPage from './components/PreviewPage'
import { StatusBar } from './components/StatusBar'
import { EditorPage } from './components/EditorPage'

type Page = 'setup' | 'preview' | 'editor'

function App() {
  const [page, setPage] = useState<Page>('setup')

  const tabClass = (active: boolean) =>
    `px-4 py-1.5 text-sm font-medium rounded border cursor-pointer transition-colors ${
      active
        ? 'bg-foreground text-background border-foreground'
        : 'bg-transparent text-foreground border-border hover:bg-muted'
    }`

  return (
    <div className="app-container">
      <h1>HuePictureControl</h1>

      <div className="flex gap-2 mb-6 border-b border-border pb-2">
        <button className={tabClass(page === 'setup')} onClick={() => setPage('setup')}>
          Setup
        </button>
        <button className={tabClass(page === 'preview')} onClick={() => setPage('preview')}>
          Preview
        </button>
        <button className={tabClass(page === 'editor')} onClick={() => setPage('editor')}>
          Editor
        </button>
      </div>

      {page === 'setup' && <PairingFlow />}
      {page === 'preview' && <PreviewPage />}
      {page === 'editor' && <EditorPage />}

      <StatusBar />
    </div>
  )
}

export default App
