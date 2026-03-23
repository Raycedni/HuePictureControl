import { useEffect, useState } from 'react'
import { pairBridge, getBridgeStatus, getEntertainmentConfigs } from '../api/hue'
import type { BridgeStatus, EntertainmentConfig } from '../api/hue'

type Step =
  | 'checking'
  | 'unpaired'
  | 'pairing'
  | 'paired'
  | 'error'

export default function PairingFlow() {
  const [step, setStep] = useState<Step>('checking')
  const [bridgeIp, setBridgeIp] = useState('')
  const [bridgeInfo, setBridgeInfo] = useState<BridgeStatus | null>(null)
  const [configs, setConfigs] = useState<EntertainmentConfig[]>([])
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    checkStatus()
  }, [])

  async function checkStatus() {
    setStep('checking')
    try {
      const status = await getBridgeStatus()
      if (status.paired) {
        setBridgeInfo(status)
        setStep('paired')
        loadConfigs()
      } else {
        setStep('unpaired')
      }
    } catch {
      setStep('unpaired')
    }
  }

  async function loadConfigs() {
    try {
      const cfgs = await getEntertainmentConfigs()
      setConfigs(cfgs)
    } catch {
      // Non-critical; display empty list
    }
  }

  async function handlePair() {
    setStep('pairing')
    try {
      const result = await pairBridge(bridgeIp)
      setBridgeInfo({
        paired: true,
        bridge_ip: result.bridge_ip,
        bridge_name: result.bridge_name,
      })
      setStep('paired')
      loadConfigs()
    } catch (err: unknown) {
      const status = (err as { status?: number }).status
      if (status === 403) {
        setErrorMessage('Press the link button on your Hue Bridge, then try again.')
      } else if (status === 502) {
        setErrorMessage('Bridge unreachable. Check the IP address and try again.')
      } else {
        setErrorMessage('Pairing failed. Please try again.')
      }
      setStep('error')
    }
  }

  if (step === 'checking') {
    return (
      <div className="pairing-flow">
        <p>Checking bridge status...</p>
      </div>
    )
  }

  if (step === 'unpaired') {
    return (
      <div className="pairing-flow">
        <h2>Pair with Hue Bridge</h2>
        <ol>
          <li>Press the <strong>link button</strong> on your Hue Bridge.</li>
          <li>Enter the bridge IP address below.</li>
          <li>Click Pair within 30 seconds.</li>
        </ol>
        <div className="pairing-form">
          <input
            type="text"
            placeholder="192.168.1.x"
            value={bridgeIp}
            onChange={(e) => setBridgeIp(e.target.value)}
          />
          <button onClick={handlePair} disabled={!bridgeIp.trim()}>
            Pair
          </button>
        </div>
      </div>
    )
  }

  if (step === 'pairing') {
    return (
      <div className="pairing-flow">
        <p>Pairing...</p>
      </div>
    )
  }

  if (step === 'paired' && bridgeInfo) {
    return (
      <div className="pairing-flow">
        <p className="paired-status">
          Paired with <strong>{bridgeInfo.bridge_name}</strong> at {bridgeInfo.bridge_ip}
        </p>
        {configs.length > 0 && (
          <div className="configs-list">
            <h3>Entertainment Configurations</h3>
            <ul>
              {configs.map((cfg) => (
                <li key={cfg.id}>
                  {cfg.name} — {cfg.channel_count} channels ({cfg.status})
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    )
  }

  if (step === 'error') {
    return (
      <div className="pairing-flow">
        <p className="error-message" style={{ color: 'red' }}>
          {errorMessage}
        </p>
        <button onClick={() => setStep('unpaired')}>Try Again</button>
      </div>
    )
  }

  return null
}
