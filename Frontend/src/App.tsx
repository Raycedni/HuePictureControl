import { useState } from 'react'
import './App.css'
import PairingFlow from './components/PairingFlow'
import PreviewPage from './components/PreviewPage'
import { StatusBar } from './components/StatusBar'
import { EditorPage } from './components/EditorPage'
import { SettingsPage } from './components/Settings/SettingsPage'

type Page = 'setup' | 'preview' | 'editor' | 'settings'

function App() {
  const [page, setPage] = useState<Page>('setup')

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="app-logo">
          <div className="app-logo-dot" />
          <h1>HuePictureControl</h1>
        </div>

        <nav className="app-nav">
          <button
            className={`app-nav-tab ${page === 'setup' ? 'active' : ''}`}
            onClick={() => setPage('setup')}
          >
            Setup
          </button>
          <button
            className={`app-nav-tab ${page === 'preview' ? 'active' : ''}`}
            onClick={() => setPage('preview')}
          >
            Preview
          </button>
          <button
            className={`app-nav-tab ${page === 'editor' ? 'active' : ''}`}
            onClick={() => setPage('editor')}
          >
            Editor
          </button>
          <button
            className={`app-nav-tab ${page === 'settings' ? 'active' : ''}`}
            onClick={() => setPage('settings')}
          >
            Settings
          </button>
        </nav>
      </header>

      <div className={`flex-1 min-h-0 flex flex-col ${page === 'editor' ? 'overflow-hidden' : 'overflow-auto'}`}>
        {page === 'setup' && <PairingFlow />}
        {page === 'preview' && <PreviewPage />}
        {page === 'editor' && <EditorPage />}
        {page === 'settings' && <SettingsPage />}
      </div>

      <StatusBar />
    </div>
  )
}

export default App
