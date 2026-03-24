import { useState } from 'react'
import './App.css'
import PairingFlow from './components/PairingFlow'
import PreviewPage from './components/PreviewPage'

type Page = 'setup' | 'preview'

function App() {
  const [page, setPage] = useState<Page>('setup')

  return (
    <div className="app-container">
      <h1>HuePictureControl</h1>

      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '2px solid #ddd', paddingBottom: '0.5rem' }}>
        <button
          onClick={() => setPage('setup')}
          style={{
            padding: '0.4rem 1.2rem',
            fontWeight: page === 'setup' ? 700 : 400,
            background: page === 'setup' ? '#333' : 'transparent',
            color: page === 'setup' ? '#fff' : '#333',
            border: '1px solid #ccc',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
        >
          Setup
        </button>
        <button
          onClick={() => setPage('preview')}
          style={{
            padding: '0.4rem 1.2rem',
            fontWeight: page === 'preview' ? 700 : 400,
            background: page === 'preview' ? '#333' : 'transparent',
            color: page === 'preview' ? '#fff' : '#333',
            border: '1px solid #ccc',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
        >
          Preview
        </button>
      </div>

      {page === 'setup' && <PairingFlow />}
      {page === 'preview' && <PreviewPage />}
    </div>
  )
}

export default App
